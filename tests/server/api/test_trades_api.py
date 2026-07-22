"""
test_trades_api.py — v10 trades query 区间查询 + 排序测试

覆盖：
- start_date/end_date 区间过滤（同时给 / 仅 start / 仅 end）
- 缺省模式: trd_date = 激活日 (向后兼容)
- 排序: trade_time DESC, trade_id DESC (二级)
- 422 校验: 非 8 位数字 → FastAPI 拒绝

复用 test_orders_api.py 的 fixture/auth/seed pattern.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))

# 注: pytest 跑时会先 import 测试模块,然后遇到 `from models.orm import ...`
#     而 models/orm.py 顶层 `from server.db import Base` 需要 server 在 sys.path.
#     把 server/ 和 project_root/ 都加进 path,绕开 pytest 基建 bug (Table 'orders' already defined).
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# Python 3.6 兼容:AsyncMock 3.8+ 才有
if sys.version_info < (3, 8):
    from unittest.mock import MagicMock as _MagicMock

    class _Call:
        def __init__(self, args, kwargs):
            self.args = args
            self.kwargs = kwargs

    class AsyncMock(_MagicMock):
        def __init__(self, *args, **kwargs):
            super(AsyncMock, self).__init__(*args, **kwargs)
            self.await_count = 0
            self.await_args = None
            self.await_args_list = []

        def __call__(self, *args, **kwargs):
            async def _coro():
                self.await_count += 1
                call = _Call(args, kwargs)
                self.await_args = call
                self.await_args_list.append(call)
                if self.side_effect is not None:
                    se = self.side_effect
                    if isinstance(se, BaseException):
                        raise se
                    if callable(se):
                        return se(*args, **kwargs)
                    return se
                return self.return_value
            return _coro()
else:
    from unittest.mock import AsyncMock

import pytest
from datetime import time

from fastapi.testclient import TestClient

from db import Base, engine, SessionLocal, init_db
from models.orm import Trade, SysStatus, TradingSession


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(bind=engine)
    init_db()
    db = SessionLocal()
    db.add(TradingSession(
        morning_start=time(9, 15), morning_end=time(11, 30),
        afternoon_start=time(13, 0), afternoon_end=time(15, 0),
    ))
    db.commit()
    db.close()
    yield


@pytest.fixture
def client():
    from main import app
    return TestClient(app)


@pytest.fixture
def active_day(fresh_db):
    """fixture: 激活 20260614 + Trader user（依赖 fresh_db 自动 drop_all）"""
    from models.user import User
    from auth.security import hash_password
    db = SessionLocal()
    db.query(User).filter_by(username="trader1").delete()
    db.commit()
    trader = User(username="trader1", password_hash=hash_password("x"), role="trader")
    db.add(trader)
    db.add(SysStatus(id=1, trd_date="20260614", status="active"))
    db.commit()
    db.refresh(trader)
    db.close()
    return trader.id


def _trader_token(user_id):
    from auth.security import create_access_token
    return create_access_token({"sub": str(user_id), "role": "trader"})


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


# ──── helpers ────

def _seed_trade(db, **kwargs):
    """构造测试 trades (默认填充必填字段, 调用方可覆盖)

    注: created_at 字段是 DateTime, 由 ORM default=_utcnow 生成, 不传字符串避免
        SQLite DateTime 报错 ("SQLite DateTime type only accepts Python datetime").
    """
    defaults = {
        "trd_date": "20260630",
        "trade_id": "T-DEFAULT",
        "trade_time": "10:00:00.000",
        "order_no": "00000001",
        "stock_code": "600030.SH",
        "order_type": "23",
        "price": 10.0,
        "volume": 100,
        "amount": 1000.0,
        "trade_type": 0,
    }
    defaults.update(kwargs)
    db.add(Trade(**defaults))


# ──── 区间查询 ────

def test_trades_with_date_range_filters_correctly(client, fresh_db, active_day):
    """start_date/end_date 同时给 → 仅返回区间内"""
    db = SessionLocal()
    try:
        _seed_trade(db, trd_date="20260628", trade_id="T1", trade_time="09:30:00.000", order_no="00000001")
        _seed_trade(db, trd_date="20260630", trade_id="T2", trade_time="10:00:00.000", order_no="00000002")
        _seed_trade(db, trd_date="20260702", trade_id="T3", trade_time="11:00:00.000", order_no="00000003")
        db.commit()
    finally:
        db.close()

    token = _trader_token(active_day)
    r = client.get(
        "/api/trades",
        params={"start_date": "20260629", "end_date": "20260701"},
        headers=_auth(token),
    )
    assert r.status_code == 200
    data = r.json()
    assert data["code"] == 0
    assert {t["trade_id"] for t in data["list"]} == {"T2"}


def test_trades_with_only_start_date_returns_open_lower_bound(client, fresh_db, active_day):
    """仅传 start_date → trd_date >= start_date"""
    db = SessionLocal()
    try:
        _seed_trade(db, trd_date="20260628", trade_id="T1", trade_time="09:30:00.000", order_no="00000001")
        _seed_trade(db, trd_date="20260630", trade_id="T2", trade_time="10:00:00.000", order_no="00000002")
        _seed_trade(db, trd_date="20260702", trade_id="T3", trade_time="11:00:00.000", order_no="00000003")
        db.commit()
    finally:
        db.close()

    token = _trader_token(active_day)
    r = client.get(
        "/api/trades",
        params={"start_date": "20260630"},
        headers=_auth(token),
    )
    assert r.status_code == 200
    data = r.json()
    assert all(t["trd_date"] >= "20260630" for t in data["list"])
    assert {t["trade_id"] for t in data["list"]} == {"T2", "T3"}


def test_trades_with_only_end_date_returns_open_upper_bound(client, fresh_db, active_day):
    """仅传 end_date → trd_date <= end_date"""
    db = SessionLocal()
    try:
        _seed_trade(db, trd_date="20260628", trade_id="T1", trade_time="09:30:00.000", order_no="00000001")
        _seed_trade(db, trd_date="20260630", trade_id="T2", trade_time="10:00:00.000", order_no="00000002")
        _seed_trade(db, trd_date="20260702", trade_id="T3", trade_time="11:00:00.000", order_no="00000003")
        db.commit()
    finally:
        db.close()

    token = _trader_token(active_day)
    r = client.get(
        "/api/trades",
        params={"end_date": "20260630"},
        headers=_auth(token),
    )
    assert r.status_code == 200
    data = r.json()
    assert all(t["trd_date"] <= "20260630" for t in data["list"])
    assert {t["trade_id"] for t in data["list"]} == {"T1", "T2"}


def test_trades_default_no_date_params_uses_active_day(client, fresh_db, active_day):
    """不传日期 → 维持现状 trd_date = 激活日 (20260614)"""
    db = SessionLocal()
    try:
        _seed_trade(db, trd_date="20260613", trade_id="T1", trade_time="09:30:00.000", order_no="00000001")
        _seed_trade(db, trd_date="20260614", trade_id="T2", trade_time="10:00:00.000", order_no="00000002")
        db.commit()
    finally:
        db.close()

    token = _trader_token(active_day)
    r = client.get("/api/trades", headers=_auth(token))
    assert r.status_code == 200
    data = r.json()
    assert {t["trade_id"] for t in data["list"]} == {"T2"}


# ──── 排序 ────

def test_trades_sorted_by_trade_time_desc(client, fresh_db, active_day):
    """排序: trade_time DESC, trade_id DESC (二级)"""
    db = SessionLocal()
    try:
        _seed_trade(db, trd_date="20260614", trade_id="T-A", trade_time="10:00:00.000", order_no="00000001")
        _seed_trade(db, trd_date="20260614", trade_id="T-B", trade_time="14:00:00.000", order_no="00000002")
        # 同 trade_time → trade_id 更大 → 二级 DESC 时排前
        _seed_trade(db, trd_date="20260614", trade_id="T-C", trade_time="14:00:00.000", order_no="00000003")
        db.commit()
    finally:
        db.close()

    token = _trader_token(active_day)
    r = client.get(
        "/api/trades",
        params={"start_date": "20260614", "end_date": "20260614"},
        headers=_auth(token),
    )
    assert r.status_code == 200
    ids = [t["trade_id"] for t in r.json()["list"]]
    assert ids == ["T-C", "T-B", "T-A"]


# ──── 422 校验 ────

def test_trades_invalid_date_format_returns_422(client, fresh_db, active_day):
    """非 8 位数字 → FastAPI 422"""
    token = _trader_token(active_day)
    r = client.get(
        "/api/trades",
        params={"start_date": "bad"},
        headers=_auth(token),
    )
    assert r.status_code == 422