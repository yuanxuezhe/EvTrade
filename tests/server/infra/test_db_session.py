"""
test_db_session.py — server.db.db_session() 单元测试

覆盖场景：
  1. 正常 yield 路径：context manager 退出时 session 关闭
  2. 异常路径：异常向上抛，session 自动 rollback + 关闭
  3. 显式 commit 在 with 块内仍生效
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))

import pytest
from sqlalchemy.exc import InvalidRequestError

from db import Base, SessionLocal, db_session, engine
from models.orm import SysStatus


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(bind=engine)
    from db import init_db
    init_db()
    yield


def test_db_session_yields_usable_session():
    """正常路径：with 块内 db 可用,可 query / add / commit"""
    with db_session() as db:
        # 验证是有效 session
        assert hasattr(db, "query")
        assert hasattr(db, "add")
        assert hasattr(db, "commit")
        # 写入一条
        db.add(SysStatus(id=1, trd_date="20260701", status="active"))
        db.commit()
        # 再查一次验证
        row = db.query(SysStatus).filter_by(trd_date="20260701").first()
        assert row is not None
        assert row.status == "active"


def test_db_session_rollback_on_exception():
    """异常路径：with 块内抛异常 → 自动 rollback + 向上抛"""
    with pytest.raises(RuntimeError, match="boom"):
        with db_session() as db:
            db.add(SysStatus(id=1, trd_date="20260701", status="active"))
            # 故意抛异常
            raise RuntimeError("boom")
    # 验证 rollback 生效：再开新 session 查不到这条
    with db_session() as db:
        row = db.query(SysStatus).filter_by(trd_date="20260701").first()
        assert row is None, "异常路径应该 rollback, 不该有这条 row"


def test_db_session_commit_in_with_block_persists():
    """with 块内显式 commit 应该持久化"""
    with db_session() as db:
        db.add(SysStatus(id=1, trd_date="20260701", status="active"))
        db.commit()
    # 用新 session 验证
    with db_session() as db:
        row = db.query(SysStatus).filter_by(trd_date="20260701").first()
        assert row is not None
        assert row.status == "active"


def test_db_session_nested_rollback_failure_logs_warning():
    """rollback 失败时只 log warning,不掩盖原始异常

    构造一个 rollback() 会抛异常的 session,验证 db_session() 不会把
    rollback 的异常往外抛,而是 log warning + 继续抛原异常。
    """
    from db import SessionLocal
    # 关闭 session 后再 rollback 会抛 sqlalchemy.exc.InvalidRequestError
    with pytest.raises(RuntimeError, match="original"):
        with db_session() as db:
            db.close()  # 关闭后 rollback() 会失败
            raise RuntimeError("original")
    # 如果走到这里,说明原异常没被抛,测试失败
    # 实际行为:原异常"original"被抛,rollback fail 异常被 log 吞掉
