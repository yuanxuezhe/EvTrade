"""
infra/db.py — SQLAlchemy 数据库基类层（v14 从 SQLite 迁移到 MySQL/pymysql）

职责：封装 MySQL + SQLAlchemy 1.4 细节，对上层暴露 Session/Base/上下文管理器。

URL 优先级（REQ-CFG-009）：
  1. EVTRADE_DB_URL 显式 → 用
  2. 否则 fallback 到 SQLite（供开发分支零依赖跑）

依赖：仅 stdlib + sqlalchemy + pymysql + cryptography + server.models（注册 ORM 元数据）。
"""
import os
import logging
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from sqlalchemy.engine import Engine

log = logging.getLogger(__name__)

# ─────────────── URL 解析 ───────────────
# 优先 EVTRADE_DB_URL，回退 SQLite 本地
_DEFAULT_SQLITE_URL = "sqlite:///./evtrade.db"

DATABASE_URL = os.environ.get("EVTRADE_DB_URL", _DEFAULT_SQLITE_URL)

# legacy 兼容常量（v13 之前 sqlite-only 时代 facade 在 server/db.py re-export）
# 新代码勿用 — 走 DATABASE_URL 即可
BASE_DIR = os.path.dirname(os.path.abspath(__file__))  # server/infra/
DB_PATH = (
    DATABASE_URL.replace("sqlite:///", "", 1)
    if DATABASE_URL.startswith("sqlite:///")
    else None
)

# ─────────────── Pool 配置（req-CFG-009）──
def _pool_kwargs(url: str) -> dict:
    """按 driver 返回 pool_kwargs. SQLite 用 StaticPool, MySQL 用常规 pool."""
    if url.startswith("sqlite"):
        # SQLite 多线程同进程需要 check_same_thread=False
        return {"connect_args": {"check_same_thread": False}}
    # MySQL / 其他关系型 DB
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

log.info("[infra.db] engine ready: driver=%s pool=%s",
         engine.dialect.name,
         "sqlite-fallback" if DATABASE_URL.startswith("sqlite") else "MySQL pool")


# ─────────────── SQLite FK enforcement（向后兼容）──
# SQLite 默认关闭外键约束（PRAGMA foreign_keys=OFF），导致 ForeignKey(ondelete="CASCADE")
# 在 DB 层不生效。MySQL/InnoDB 自动 enforce FK，无需 PRAGMA。
# 此 hook 仅在 SQLite 连接上触发，MySQL skip。
@event.listens_for(Engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    """Driver-aware connect hook: 只 SQLite 启用 PRAGMA foreign_keys=ON."""
    if not DATABASE_URL.startswith("sqlite"):
        return
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


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
