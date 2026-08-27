"""
server/tests/conftest.py — 测试公共 fixture (单一事实源)

TEST_TRD_DATE: 测试数据隔离日期 (2026-08-27 用户硬规则: 不删生产数据).
  高位前缀 99990718 与生产 trd_date (202608xx) 永不冲突, 测试写入
  orders.trd_date='99990718' 的行**只可能来自测试** (生产流程从不会写该日期),
  因此对该日期的清理是安全的.
"""
import pytest

TEST_TRD_DATE = "99990718"


@pytest.fixture(autouse=True)
def clean_test_orders():
    """autouse finalizer: 清 TEST_TRD_DATE 日期下的全部 orders 残留.

    该日期是测试专属隔离日期 (生产永不写入), 清理安全. 解决:
    - 跨文件污染 (place 的 seed 行混进 cancel 的 trd_date 查询)
    - 历史残留 (v1 标记引入前测试跑出来的 user_def='' 行)
    各测试文件的 db fixture 再叠加按 user_def 标记的清理 (双保险).
    """
    from sqlalchemy import text
    from server.infra.db import SessionLocal
    s = SessionLocal()
    yield
    s.execute(text("DELETE FROM orders WHERE trd_date = :d"), {"d": TEST_TRD_DATE})
    s.commit()
    s.close()


@pytest.fixture
def mock_trd_date(monkeypatch):
    """隔离 trd_date: monkeypatch _get_active_trd_date → TEST_TRD_DATE, 同时返回该值.

    两个用途合一:
    - place 主流程内部调 _get_active_trd_date → patch 后自动用 TEST_TRD_DATE
    - cancel 等端点显式接 Query param trd_date → 测试直接用返回值传 query

    注意: 对不走 _get_active_trd_date 的流程 (如 cancel 端点) patch 是无害 no-op,
    因此本 fixture 可被所有 server/tests 测试共用.
    """
    from server.repo import orders as repo_orders

    def _fake_get_active_trd_date(db=None) -> str:
        return TEST_TRD_DATE

    monkeypatch.setattr(repo_orders, "_get_active_trd_date", _fake_get_active_trd_date)
    # 同步 patch re-export 链上的别名 (place.py: from server.repo.orders import _get_active_trd_date)
    from server.api.orders import place as place_mod
    monkeypatch.setattr(place_mod, "_get_active_trd_date", _fake_get_active_trd_date)
    return TEST_TRD_DATE
