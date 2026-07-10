"""
infra/db.py — SQLAlchemy 数据库基类层（v14 从 SQLite 迁移到 MySQL/pymysql，v20 强制 MySQL-only）

职责：封装 MySQL + SQLAlchemy 1.4 细节，对上层暴露 Session/Base/上下文管理器。

URL 优先级（REQ-CFG-009 v20 永久标准）：
  1. EVTRADE_DB_URL 显式 → 用
  2. 否则 **RuntimeError**（永久禁用 SQLite fallback，运维必须 .env 配齐 MySQL URL）

依赖：仅 stdlib + sqlalchemy + pymysql + cryptography + server.models（注册 ORM 元数据）。
"""
import os
import logging
from contextlib import contextmanager

# 2026-07-10 fix: server.config 才会 load_dotenv(server/.env)，但 infra/db.py
# 不依赖 config (legacy 兼容),导致模块级 os.environ.get('EVTRADE_DB_URL')
# 永远拿不到 .env 里的值 → fallback SQLite。
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

# ─────────────── URL 解析（v20 MySQL-only 永久标准） ───────────────
# 永久禁用 SQLite fallback：未设 EVTRADE_DB_URL 直接 RuntimeError。
# 历史背景：v14 引入 MySQL/pymysql 默认 URL 但保留 sqlite:///./evtrade.db 作 dev fallback；
# v20 起下线 fallback，本项目只允许 MySQL/pymysql。
try:
    DATABASE_URL = os.environ["EVTRADE_DB_URL"]
except KeyError:
    raise RuntimeError(
        "[infra.db] EVTRADE_DB_URL is required (v20 MySQL-only permanent standard). "
        "Set it in server/.env, e.g. mysql+pymysql://EvTrade:p%40ssw0rd@127.0.0.1:33066/evtrade?charset=utf8mb4"
    )
if not DATABASE_URL.startswith("mysql"):
    raise RuntimeError(
        f"[infra.db] Only MySQL is supported (v20 permanent standard). "
        f"Got URL: {DATABASE_URL[:80]!r}. SQLite has been permanently disabled."
    )

# BASE_DIR 保留以兼容 import
BASE_DIR = os.path.dirname(os.path.abspath(__file__))  # server/infra/

# ─────────────── Pool 配置（v20 MySQL-only）──
def _pool_kwargs(url: str) -> dict:
    """v20 只支持 MySQL，返回固定 pool_kwargs。"""
    assert url.startswith("mysql"), f"_pool_kwargs called with non-MySQL URL: {url[:80]}"
    size = int(os.environ.get("EVTRADE_DB_POOL_SIZE", "5"))
    ofl = int(os.environ.get("EVTRADE_DB_MAX_OVERFLOW", "10"))
    rec = int(os.environ.get("EVTRADE_DB_POOL_RECYCLE", "1800"))
    pre_ping = os.environ.get("EVTRADE_DB_POOL_PRE_PING", "true").lower() == "true"
    return {
        "pool_size": size,
        "max_overflow": ofl,
        "pool_recycle": rec,
        "pool_pre_ping": pre_ping,
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
    "expected 'mysql'. v20 MySQL-only standard violated."
)

log.info("[infra.db] engine ready: driver=mysql pool_size=%d max_overflow=%d",
         _engine_kwargs["pool_size"], _engine_kwargs["max_overflow"])


# ─────────────── MySQL connect hook（v20 起无 SQLite 兼容逻辑）──
# 原 v14 时期有 _set_sqlite_pragma hook 仅在 SQLite 连接上启用 PRAGMA foreign_keys=ON。
# v20 起 SQLite 永久禁用，整个 hook 删除 — MySQL/InnoDB 自动 enforce FK，无需 PRAGMA。
# 保留一个 no-op event listener 占位以兼容未来 MySQL session-level init（如 SET time_zone）。
@event.listens_for(Engine, "connect")
def _on_connect(dbapi_connection, connection_record):
    """v20 MySQL-only: no-op placeholder, MySQL/InnoDB handles FK enforce natively."""
    pass


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """FastAPI dependency: yields a database session and closes it after use."""
    db = SessionLocal()
    try:
        yield db
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
    from server.services.strategy import models as strategy_models  # noqa: F401
    from sqlalchemy import text

    # v20: admin engine 重新计算 pool_kwargs (不重用模块级 _engine_kwargs)
    # 之前复用 _engine_kwargs 在 SQLite fallback 场景会把 check_same_thread 传给 MySQL
    # admin engine (pymysql 不识别该参数 → TypeError)
    admin_url = os.environ.get("EVTRADE_DB_ADMIN_URL", DATABASE_URL)
    admin_engine = create_engine(admin_url, **_pool_kwargs(admin_url))

    Base.metadata.create_all(bind=admin_engine)

    # change strategy_trade: 为 orders.user_def 加索引
    # SQLite IF NOT EXISTS；MySQL 用 INFORMATION_SCHEMA 探测
    idx_name = "ix_orders_user_def"
    table = "orders"
    col = "user_def"

    with admin_engine.begin() as conn:
        if admin_engine.dialect.name == "mysql":
            row = conn.execute(text("""
                SELECT 1 FROM INFORMATION_SCHEMA.STATISTICS
                 WHERE TABLE_SCHEMA = DATABASE()
                   AND TABLE_NAME   = :t
                   AND INDEX_NAME   = :n
                 LIMIT 1
            """), {"t": table, "n": idx_name}).first()
            if row is None:
                conn.execute(text(f"CREATE INDEX {idx_name} ON {table} ({col})"))
        else:
            conn.execute(text(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table} ({col})"))

    admin_engine.dispose()
