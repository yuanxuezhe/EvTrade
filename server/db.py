"""
SQLite database setup (SQLAlchemy 1.4)
"""
import os
import logging
from contextlib import contextmanager
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base, Session

log = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "evtrade.db")
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,
)


# ─────────────── SQLite FK enforcement ───────────────
# SQLite 默认关闭外键约束（PRAGMA foreign_keys=OFF），导致 ForeignKey(ondelete="CASCADE")
# 在 DB 层不生效；ORM 层 cascade 仅处理已加载对象，未加载/孤儿行不会被清。
# 用 connect 事件为每个新连接启用 PRAGMA，让所有 FK ON DELETE CASCADE 真正生效。
@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
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
    """Create all tables. Called at startup."""
    # Import models so they are registered on the metadata
    from server.models import user, orm  # noqa: F401
    from server.services.strategy import models as strategy_models  # noqa: F401  # change strategy_trade
    Base.metadata.create_all(bind=engine)
    # change strategy_trade: 给已存在的 orders 表加 ix_orders_user_def 索引
    # （SQLAlchemy create_all 对已存在表是幂等空操作，新索引需手动 IF NOT EXISTS）
    with engine.begin() as conn:
        from sqlalchemy import text
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_orders_user_def ON orders(user_def)"))
