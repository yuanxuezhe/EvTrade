"""
infra/db.py — SQLAlchemy 数据库基类层（MySQL-only）

职责：封装 MySQL + SQLAlchemy 1.4 细节，对上层暴露 Session/Base/上下文管理器。

URL 优先级（REQ-CFG-009 永久标准）：
  1. EVTRADE_DB_URL 显式 → 用
  2. 否则 **RuntimeError**（运维必须 .env 配齐 MySQL URL）

依赖：仅 stdlib + sqlalchemy + pymysql + cryptography + server.models（注册 ORM 元数据）。
"""
import os
import logging
from contextlib import contextmanager

# server.config 才会 load_dotenv(server/.env)，但 infra/db.py
# 不依赖 config (legacy 兼容),导致模块级 os.environ.get('EVTRADE_DB_URL')
# 永远拿不到 .env 里的值。
# 这里自行 load_dotenv 一次（idempotent, 与 config.load_dotenv override=False 不冲突）。
try:
    from dotenv import load_dotenv
    _ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
    if os.path.exists(_ENV_PATH):
        load_dotenv(_ENV_PATH, override=False)
except ImportError:
    pass

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from sqlalchemy.engine import Engine

log = logging.getLogger(__name__)

# ─────────────── URL 解析（MySQL-only 永久标准） ───────────────
# MySQL 唯一：未设 EVTRADE_DB_URL 直接 RuntimeError，本项目只允许 MySQL/pymysql。
try:
    DATABASE_URL = os.environ["EVTRADE_DB_URL"]
except KeyError:
    raise RuntimeError(
        "[infra.db] EVTRADE_DB_URL is required (MySQL-only permanent standard). "
        "Set it in server/.env, e.g. mysql+pymysql://EvTrade:p%40ssw0rd@127.0.0.1:33066/evtrade?charset=utf8mb4"
    )
if not DATABASE_URL.startswith("mysql"):
    raise RuntimeError(
        f"EVTRADE_DB_URL is required (must start with mysql+pymysql://). "
        f"Got URL: {DATABASE_URL[:80]!r}."
    )

# BASE_DIR 保留以兼容 import
BASE_DIR = os.path.dirname(os.path.abspath(__file__))  # server/infra/

# ─────────────── Pool 配置（MySQL-only）──
def _pool_kwargs(url: str) -> dict:
    """只支持 MySQL，返回固定 pool_kwargs。

    pool_timeout 默认 10s（SQLAlchemy 默认 30s）。

    历史事故教训（futex 僵死）:
      旧 sync login endpoint 内 bcrypt.checkpw (~250ms) 阻塞 Starlette anyio
      threadpool (默认 40 线程) → 其他 sync endpoint 抢不到线程 → DB session
      在 handler 内 commit 后无法归还 → pool 5+10=15 耗尽 → 新请求 30s 等连接
      → futex_wait 永久僵死。
    根治: login/change-password 已改 async，bcrypt 走 run_in_threadpool
    → 释放 anyio threadpool → DB session 立即归还 → pool 不爆 → futex 不触发。

    pool_timeout=10 仍保留作为兜底：极端情况下仍超时则快速 5xx，
    而不是让主进程卡 30s + 僵死。
    """
    assert url.startswith("mysql"), f"_pool_kwargs called with non-MySQL URL: {url[:80]}"
    # 单进程部署: 进程内只有 1 个 pool, 需承担全部并发.
    # 默认上调: pool_size=20 + max_overflow=30 = 50 (远低于 MySQL 默认 151 max_connections).
    # 仍可被环境变量覆盖 (e.g. MySQL max_connections 受限的小机器).
    size = int(os.environ.get("EVTRADE_DB_POOL_SIZE", "20"))
    ofl = int(os.environ.get("EVTRADE_DB_MAX_OVERFLOW", "30"))
    rec = int(os.environ.get("EVTRADE_DB_POOL_RECYCLE", "1800"))
    pre_ping = os.environ.get("EVTRADE_DB_POOL_PRE_PING", "true").lower() == "true"
    timeout = int(os.environ.get("EVTRADE_DB_POOL_TIMEOUT", "10"))
    return {
        "pool_size": size,
        "max_overflow": ofl,
        "pool_recycle": rec,
        "pool_pre_ping": pre_ping,
        "pool_timeout": timeout,
    }


_engine_kwargs = {
    "echo": False,
    "future": True,
}
_engine_kwargs.update(_pool_kwargs(DATABASE_URL))

engine = create_engine(DATABASE_URL, **_engine_kwargs)

# 启动时 dialect 断言（双重保险）
assert engine.dialect.name == "mysql", (
    f"[infra.db] FATAL: engine dialect is {engine.dialect.name!r}, "
    "expected 'mysql'. MySQL-only standard violated."
)

log.info("[infra.db] engine ready: driver=mysql pool_size=%d max_overflow=%d",
         _engine_kwargs["pool_size"], _engine_kwargs["max_overflow"])


# ─────────────── MySQL connect hook ──
# MySQL/InnoDB 自动 enforce FK，无需 PRAGMA。
# 保留一个 no-op event listener 占位以兼容未来 MySQL session-level init（如 SET time_zone）。
@event.listens_for(Engine, "connect")
def _on_connect(dbapi_connection, connection_record):
    """MySQL-only: no-op placeholder, MySQL/InnoDB handles FK enforce natively."""
    pass


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """FastAPI dependency: yields a database session and closes it after use.

    futex 僵死教训：
      旧 sync endpoint (login) 阻塞 Starlette threadpool → DB session 在
      handler 内 db.commit() 后无法走到 finally → 连接泄漏 → pool 满 → 僵死。

    现在的兜底机制（即便 endpoint 误用 sync 阻塞）：
      - try/finally 保证 close() 被调用
      - 异常时 rollback + close（防止 session 半挂状态）
      - 上游 _pool_kwargs pool_timeout=10 兜底防 futex
    """
    db = SessionLocal()
    try:
        yield db
    except Exception:
        # 异常路径：rollback 后再 close，避免半挂连接
        try:
            db.rollback()
        except Exception:
            pass
        raise
    finally:
        db.close()


@contextmanager
def db_session():
    """服务层短连接 Session context manager.

    用于 DI 不可用的场景（event-loop coroutine / 背景 task / class method）。
    自动关闭 + 异常时 rollback（caller 自行决定是否 commit），
    替代散落各处的 `db = SessionLocal(); try/finally: db.close()` 样板。

    用法:
        with db_session() as db:
            row = db.query(Foo).first()
            db.add(bar); db.commit()
    """
    db: Session = SessionLocal()
    try:
        yield db
    except Exception:
        try:
            db.rollback()
        except Exception as e:
            log.warning("db_session rollback failed: %s", e)
        raise
    finally:
        db.close()


def init_db():
    """Create all tables + orders index.

    首次部署用；重复调用幂等（CREATE TABLE IF NOT EXISTS）。

    DDL 权限：要求 admin-level URL (CREATE/INDEX/REFERENCES)。
    通过 `EVTRADE_DB_ADMIN_URL` 提供；未设置时降级用 `EVTRADE_DB_URL`
    （如果业务用户没 DDL 权限会报错，提示运维读 spec REQ-CFG-009）。

    生产环境推荐：跑一次后即把 admin URL 从 env 移除（避免 runtime 错用）。
    """
    from server.models import user, orm  # noqa: F401
    from sqlalchemy import text

    # admin engine 重新计算 pool_kwargs (不重用模块级 _engine_kwargs)
    admin_url = os.environ.get("EVTRADE_DB_ADMIN_URL", DATABASE_URL)
    admin_engine = create_engine(admin_url, **_pool_kwargs(admin_url))

    Base.metadata.create_all(bind=admin_engine)

    # stocks 加 stktype + scale 两列（幂等 — 仅在列不存在时 ALTER）
    # 业务：stktype=0(股票)/1(ETF) 用户手动维护；scale=价格小数位精度 默认 2
    _ensure_stocks_columns(admin_engine)

    # sys_config 兜底初始化 cantrdstktypes=0,1
    _run_seed_cantrdstktypes_via_session(admin_engine)

    # change strategy_trade: 为 orders.user_def 加索引
    # MySQL: 用 INFORMATION_SCHEMA 探测索引存在性
    idx_name = "ix_orders_user_def"
    table = "orders"
    col = "user_def"

    with admin_engine.begin() as conn:
        row = conn.execute(text("""
            SELECT 1 FROM INFORMATION_SCHEMA.STATISTICS
             WHERE TABLE_SCHEMA = DATABASE()
               AND TABLE_NAME   = :t
               AND INDEX_NAME   = :n
             LIMIT 1
        """), {"t": table, "n": idx_name}).first()
        if row is None:
            conn.execute(text(f"CREATE INDEX {idx_name} ON {table} ({col})"))

    admin_engine.dispose()


def _ensure_stocks_columns(engine) -> None:
    """stocks.stktype + stocks.scale 幂等迁移。

    用 INFORMATION_SCHEMA.COLUMNS 探测列存在性，缺失则 ALTER TABLE ADD COLUMN。
    重入 init_db() 时幂等（已存在则跳过）。
    """
    from sqlalchemy import text

    target_cols = [
        ("stktype", "SMALLINT", "0", "证券类型 0=股票 1=ETF"),
        ("scale",   "SMALLINT", "2", "价格小数位精度"),
    ]

    with engine.begin() as conn:
        for col_name, col_type, default_val, col_comment in target_cols:
            row = conn.execute(text("""
                SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
                 WHERE TABLE_SCHEMA = DATABASE()
                   AND TABLE_NAME   = 'stocks'
                   AND COLUMN_NAME   = :c
                 LIMIT 1
            """), {"c": col_name}).first()
            if row is None:
                # MySQL 8.0: ALTER ... ADD COLUMN ... NOT NULL DEFAULT ... COMMENT ...
                conn.execute(text(
                    f"ALTER TABLE stocks ADD COLUMN {col_name} {col_type} "
                    f"NOT NULL DEFAULT {default_val} COMMENT '{col_comment}'"
                ))
                print(f"[init_db] ADD COLUMN stocks.{col_name} ({col_type} DEFAULT {default_val})")
            else:
                print(f"[init_db] stocks.{col_name} 已存在, 跳过")


def _seed_cantrdstktypes() -> None:
    """sys_config 兜底初始化 cantrdstktypes=0,1 (可交易股票/ETF).

    与 _ensure_defaults 同模式: idempotent, 若键已存在则跳过.
    """
    try:
        from server.infra.db import SessionLocal
        from server.repo.sysconfig import set_value
        from server.repo.sysconfig import get_value
        existing = get_value("system", "cantrdstktypes")
        if existing is None:
            set_value(
                user="system",
                key="cantrdstktypes",
                value="0,1",
                desc="可交易的证券类型 (stktype 逗号分隔, e.g. 0,1)",
            )
            print("[init_db] seeded sys_config.cantrdstktypes=0,1")
        else:
            print(f"[init_db] sys_config.cantrdstktypes 已存在 val={existing}, 跳过")
    except Exception as e:
        print(f"[init_db] seed cantrdstktypes WARN: {e}")


def _run_seed_cantrdstktypes_via_session(engine) -> None:
    """用同一 admin_engine 跑 seed, 避免引入额外 db 连接

    写到 user='0' 默认区, 与其他 sysconfig 配置保持一致
    sys_config 实际列名是 cfg_key + cfg_val (不是 key+val)
    """
    from sqlalchemy import text
    try:
        with engine.begin() as conn:
            row = conn.execute(text(
                "SELECT cfg_val FROM sys_config WHERE `user`='0' AND cfg_key='cantrdstktypes' LIMIT 1"
            )).first()
            if row is None:
                conn.execute(text(
                    "INSERT INTO sys_config (`user`, cfg_key, cfg_val, `desc`, updated_at, updated_by) "
                    "VALUES ('0', 'cantrdstktypes', '0,1', '可交易的证券类型 (stktype 逗号分隔)', NOW(), 'system')"
                ))
                print("[init_db] seeded sys_config.cantrdstktypes=0,1")
            else:
                print(f"[init_db] sys_config.cantrdstktypes 已存在 val={row[0]}, 跳过")
    except Exception as e:
        print(f"[init_db] seed cantrdstktypes WARN: {e}")


# _admin_engine 占位 (兼容旧引用)
_admin_engine = None



