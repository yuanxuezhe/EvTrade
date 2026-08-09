"""
strategy_exec.data_access.db — SQLAlchemy engine + session

📌 共享 EvTrade 的 MySQL (EVTRADE_DB_URL, 同库 strategy_script / strategy_task / strategy_script_audit)
   表结构由 server/schema.yml + sync_schema.py 维护, strategy_exec 仅消费
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from strategy_exec.config import get_settings

log = logging.getLogger(__name__)

_engine: Optional[Engine] = None
_session_factory: Optional[sessionmaker] = None


def get_engine() -> Engine:
    """返 SQLAlchemy engine (单例, lazy init)"""
    global _engine, _session_factory
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(
            settings.evtrade_db_url,
            pool_size=settings.evtrade_db_pool_size,
            max_overflow=settings.evtrade_db_max_overflow,
            pool_recycle=settings.evtrade_db_pool_recycle,
            pool_pre_ping=settings.evtrade_db_pool_pre_ping,
            echo=False,
        )
        _session_factory = sessionmaker(bind=_engine, expire_on_commit=False)
        log.info("[db] engine created (pool_size=%d)", settings.evtrade_db_pool_size)
    return _engine


def get_session() -> Session:
    """返新 Session (caller 负责 close)"""
    if _session_factory is None:
        get_engine()
    assert _session_factory is not None
    return _session_factory()


@contextmanager
def session_scope() -> Iterator[Session]:
    """with 上下文自动 commit/rollback"""
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def dispose_engine() -> None:
    """应用关闭时调用"""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None


def health_check() -> bool:
    """快速 DB 连通性检查"""
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        log.error("[db] health_check failed: %s", e)
        return False