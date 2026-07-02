"""
SQLite database setup (SQLAlchemy 1.4)
"""
import os
import logging
from contextlib import contextmanager
from sqlalchemy import create_engine
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
    Base.metadata.create_all(bind=engine)
