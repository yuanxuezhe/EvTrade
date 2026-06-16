"""
test_orders_api.py — 验证 v7 下单/撤单/查询（schema refinement）

mock RPC + TradingClock，覆盖：
- v7: 幂等改由 order_no 单调递增保证（每次调用都创建新 Order）
- v7: user_def 透传到 Order.user_def
- 屏障（未激活 / 非时段拒绝）
- 下单成功 → status=49,broker 带回 order_id 时写入
- 下单成功 → broker 不带回 order_id 时 order_id 为空
- 下单失败 → status=55 废单
- 撤单成功 → 不本地改 status
- 撤单失败 → 500
- 撤单时 broker order_id 还没回报 → BROKER_NOT_READY
- 查询 DB

v6 改动（order-pk-by-orderno）：
- 复合主键 (trd_date, order_no)；order_id 可空,broker ack/ord_cfm 到达时填入
- DELETE /{order_no} 路径,内部用 order.order_id 调 RPC
- OrderOut.order_id 默认空串,broker 未回报前为空
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))

# Python 3.6 兼容:AsyncMock 3.8+ 才有
if sys.version_info < (3, 8):
    from unittest.mock import MagicMock as _MagicMock

    class _Call:
        def __init__(self, args, kwargs):
            self.args = args
            self.kwargs = kwargs

    class AsyncMock(_MagicMock):
        """AsyncMock 兼容垫片(3.6 友好版)

        跟踪 await_count / await_args / await_args_list,模拟 3.8+ AsyncMock 行为。
        """
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
                # side_effect 处理
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
from datetime import datetime, time, timedelta
from unittest.mock import patch, MagicMock

from fastapi import HTTPException
from fastapi.testclient import TestClient

from db import Base, engine, SessionLocal, init_db, get_db
from models.orm import Order, SysStatus, TradingSession


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
    db.add(SysStatus(trd_date="20260614", status="active"))
    db.commit()
    db.refresh(trader)
    db.close()
    return trader.id


def _trader_token(user_id: int) -> str:
    from auth.security import create_access_token
    return create_access_token({"sub": str(user_id), "role": "trader"})


def _auth(t: str) -> dict:
    return {"Authorization": f"Bearer {t}"}


# ──── 屏障：未做日初 → 拒绝 ────

@pytest.fixture
def no_active_day(fresh_db):
    from models.user import User
    from auth.security import hash_password
    db = SessionLocal()
    db.query(User).filter_by(username="trader1").delete()
    db.commit()
    trader = User(username="trader1", password_hash=hash_password("x"), role="trader")
    db.add(trader)
    db.commit()
    db.refresh(trader)
    db.close()
    return trader.id


def test_place_blocked_when_no_active_trading_day(client, no_active_day, monkeypatch):
    """没激活交易日 → POST /place 返回 503"""
    monkeypatch.setattr(
        "services.trading_clock.TradingClock.is_in_trading_session",
        classmethod(lambda cls: True)
    )
    r = client.post(
        "/api/orders/place",
        json={
            "user_def": "CID1",
            "stock_code": "600030.SH",
            "order_type": "23",
            "volume": 100,
            "price": 12.5,
            "price_type": 11,
        },
        headers=_auth(_trader_token(no_active_day)),
    )
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "TRADING_DAY_NOT_INIT"
    assert r.json()["detail"]["redirect"] == "/admin/sys-status"


def test_get_works_when_no_active_trading_day(client, active_day):
    """未做日初 → 查询允许"""
    r = client.get("/api/orders", headers=_auth(_trader_token(active_day)))
    assert r.status_code == 200
    assert r.json()["code"] == 0


# ──── 屏障：非交易时段 → 拒绝 ────

def test_place_blocked_outside_session(client, active_day, monkeypatch):
    monkeypatch.setattr(
        "services.trading_clock.TradingClock.is_in_trading_session",
        classmethod(lambda cls: False)
    )
    r = client.post(
        "/api/orders/place",
        json={"user_def": "CID1", "stock_code": "600030.SH",
              "order_type": "23", "volume": 100, "price": 12.5, "price_type": 11},
        headers=_auth(_trader_token(active_day)),
    )
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "OUTSIDE_TRADING_SESSION"


# ──── v7 幂等改由 order_no 单调递增保证 ────

def test_place_each_call_creates_new_order_v7(client, active_day, monkeypatch):
    """v7: 删 client_order_id UNIQUE 约束,幂等改由 order_no 单调递增保证
    每次调用都生成新 order_no,broker 端重复 remark 由 broker 拒收
    """
    monkeypatch.setattr(
        "services.trading_clock.TradingClock.is_in_trading_session",
        classmethod(lambda cls: True)
    )
    mock_rpc = AsyncMock(return_value={"code": 0, "msg": "ok", "list": [{"order_id": "OID1"}]})
    monkeypatch.setattr("api.orders.ord_stk", mock_rpc)
    headers = _auth(_trader_token(active_day))
    body = {
        "user_def": "USER-DEF-A",
        "stock_code": "600030.SH",
        "order_type": "23",
        "volume": 100,
        "price": 12.5,
        "price_type": 11,
    }
    r1 = client.post("/api/orders/place", json=body, headers=headers)
    assert r1.status_code == 200
    order_no_1 = r1.json()["order"]["order_no"]

    # v7: 第二次调用不幂等 — 创建新 Order,order_no 单调递增
    r2 = client.post("/api/orders/place", json=body, headers=headers)
    assert r2.status_code == 200
    order_no_2 = r2.json()["order"]["order_no"]

    assert order_no_1 != order_no_2
    # broker 端调用次数 = 2(v7 不再应用层 dedup)
    assert mock_rpc.await_count == 2


def test_place_passes_user_def_to_order(client, active_day, monkeypatch):
    """v7: user_def 透传到 Order.user_def"""
    monkeypatch.setattr(
        "services.trading_clock.TradingClock.is_in_trading_session",
        classmethod(lambda cls: True)
    )
    mock_rpc = AsyncMock(return_value={"code": 0, "msg": "ok", "list": [{"order_id": "OID1"}]})
    monkeypatch.setattr("api.orders.ord_stk", mock_rpc)
    headers = _auth(_trader_token(active_day))
    body = {
        "user_def": "external-tag-12345",
        "stock_code": "600030.SH",
        "order_type": "23",
        "volume": 100,
        "price": 12.5,
        "price_type": 11,
    }
    r = client.post("/api/orders/place", json=body, headers=headers)
    assert r.status_code == 200
    assert r.json()["order"]["user_def"] == "external-tag-12345"


# ──── 下单成功 broker 带回 order_id → 写入 ────

def test_place_success_with_broker_order_id_writes(client, active_day, monkeypatch):
    """broker ack 带回 order_id → 写入 Order.order_id"""
    monkeypatch.setattr(
        "services.trading_clock.TradingClock.is_in_trading_session",
        classmethod(lambda cls: True)
    )
    mock_rpc = AsyncMock(return_value={"code": 0, "msg": "ok", "list": [{"order_id": "BROKER-OID-1"}]})
    monkeypatch.setattr("api.orders.ord_stk", mock_rpc)
    mock_ws = AsyncMock()
    monkeypatch.setattr("api.orders.ws_manager.broadcast", mock_ws)

    r = client.post(
        "/api/orders/place",
        json={"user_def": "CID-OK", "stock_code": "600030.SH",
              "order_type": "23", "volume": 100, "price": 12.5, "price_type": 11},
        headers=_auth(_trader_token(active_day)),
    )
    assert r.status_code == 200
    body = r.json()["order"]
    assert body["status"] == "49"
    assert body["order_id"] == "BROKER-OID-1"
    assert body["order_no"] == "10000001"
    assert body["trd_date"] == "20260614"
    assert mock_rpc.await_count == 1
    # 校验传给柜台的 remark
    call_kwargs = mock_rpc.await_args.kwargs
    assert call_kwargs["remark"] == "10000001"
    # 推 WS
    assert mock_ws.await_count == 1

    # DB 验证
    db = SessionLocal()
    row = db.query(Order).filter_by(order_no="10000001").first()
    assert row.order_id == "BROKER-OID-1"
    assert row.status == "49"
    db.close()


# ──── 下单成功 broker 不带回 order_id → 留空 ────

def test_place_success_no_broker_order_id_leaves_empty(client, active_day, monkeypatch):
    """broker ack 不带回 order_id → 响应 order_id=\"\";DB 留空"""
    monkeypatch.setattr(
        "services.trading_clock.TradingClock.is_in_trading_session",
        classmethod(lambda cls: True)
    )
    # broker 协议可能不送 order_id(只回 ack)
    mock_rpc = AsyncMock(return_value={"code": 0, "msg": "ok", "list": [{}]})
    monkeypatch.setattr("api.orders.ord_stk", mock_rpc)

    r = client.post(
        "/api/orders/place",
        json={"user_def": "CID-NO-OID", "stock_code": "600030.SH",
              "order_type": "23", "volume": 100, "price": 12.5, "price_type": 11},
        headers=_auth(_trader_token(active_day)),
    )
    assert r.status_code == 200
    body = r.json()["order"]
    # v6: 响应 order_id = "" (broker 没回报),不再有 PENDING- 占位
    assert body["order_id"] == ""
    assert body["status"] == "49"  # 仍写 49
    assert body["order_no"] == "10000001"
    assert "PENDING" not in body["order_id"]  # 显式断言:不再出现 PENDING-

    # DB 验证:order_id 留空
    db = SessionLocal()
    row = db.query(Order).filter_by(order_no="10000001").first()
    assert row.order_id is None or row.order_id == ""
    db.close()


# ──── 下单失败 → status=55 废单 ────

def test_place_rpc_fail_marks_rejected(client, active_day, monkeypatch):
    monkeypatch.setattr(
        "services.trading_clock.TradingClock.is_in_trading_session",
        classmethod(lambda cls: True)
    )
    mock_rpc = AsyncMock(side_effect=Exception("柜台断连"))
    monkeypatch.setattr("api.orders.ord_stk", mock_rpc)

    r = client.post(
        "/api/orders/place",
        json={"user_def": "CID-FAIL", "stock_code": "600030.SH",
              "order_type": "23", "volume": 100, "price": 12.5, "price_type": 11},
        headers=_auth(_trader_token(active_day)),
    )
    assert r.status_code == 200
    body = r.json()["order"]
    assert body["status"] == "55"
    assert "RPC 失败" in body["status_msg"]


# ──── 撤单(v6:用 order_no) ────

def test_cancel_calls_rpc_does_not_change_status(client, active_day, monkeypatch):
    """v6: DELETE /{order_no} 调 RPC,order.order_id 传给 cancel_ord"""
    monkeypatch.setattr(
        "services.trading_clock.TradingClock.is_in_trading_session",
        classmethod(lambda cls: True)
    )
    db = SessionLocal()
    db.add(Order(
        trd_date="20260614",
        order_id="OID-X", user_def="CID-X", order_no="10000010",
        stock_code="600030.SH", order_type="23", price_type=11, price=12.5, volume=100,
        status="49",
    ))
    db.commit()
    db.close()

    mock_rpc = AsyncMock(return_value={"code": 0, "msg": "ok", "list": []})
    monkeypatch.setattr("api.orders.rpc_cancel_order", mock_rpc)

    r = client.delete(
        "/api/orders/10000010?trd_date=20260614",  # v6: 用 order_no
        headers=_auth(_trader_token(active_day)),
    )
    assert r.status_code == 200
    # RPC 用查到的 broker order_id (不是 URL 参数)
    call_kwargs = mock_rpc.await_args.kwargs
    assert call_kwargs["order_id"] == "OID-X"
    # 状态没改(等 push)
    db = SessionLocal()
    row = db.query(Order).filter_by(order_no="10000010", trd_date="20260614").first()
    assert row.status == "49"
    db.close()


def test_cancel_broker_not_ready_returns_business_error(client, active_day, monkeypatch):
    """v6: 撤单时 broker order_id 还没回报 → BROKER_NOT_READY,不调 RPC"""
    monkeypatch.setattr(
        "services.trading_clock.TradingClock.is_in_trading_session",
        classmethod(lambda cls: True)
    )
    db = SessionLocal()
    db.add(Order(
        trd_date="20260614",
        order_id=None,  # v6: broker 还没回报
        user_def="CID-PENDING", order_no="10000011",
        stock_code="600030.SH", order_type="23", price_type=11, price=12.5, volume=100,
        status="48",  # 待报
    ))
    db.commit()
    db.close()

    mock_rpc = AsyncMock(return_value={"code": 0, "msg": "ok", "list": []})
    monkeypatch.setattr("api.orders.rpc_cancel_order", mock_rpc)

    r = client.delete(
        "/api/orders/10000011?trd_date=20260614",
        headers=_auth(_trader_token(active_day)),
    )
    assert r.status_code == 200  # 不是 HTTP 错误,是业务码
    body = r.json()
    assert body["code"] == 1
    assert body["error"] == "BROKER_NOT_READY"
    assert mock_rpc.await_count == 0  # RPC 不会被调


def test_cancel_rpc_fail_returns_500(client, active_day, monkeypatch):
    monkeypatch.setattr(
        "services.trading_clock.TradingClock.is_in_trading_session",
        classmethod(lambda cls: True)
    )
    db = SessionLocal()
    db.add(Order(
        trd_date="20260614",
        order_id="OID-Y", user_def="CID-Y", order_no="10000020",
        stock_code="600030.SH", order_type="23", price_type=11, price=12.5, volume=100,
        status="49",
    ))
    db.commit()
    db.close()

    mock_rpc = AsyncMock(side_effect=Exception("rpc 断连"))
    monkeypatch.setattr("api.orders.rpc_cancel_order", mock_rpc)

    r = client.delete(
        "/api/orders/10000020?trd_date=20260614",  # v6: order_no
        headers=_auth(_trader_token(active_day)),
    )
    assert r.status_code == 500


def test_cancel_not_found_returns_404(client, active_day, monkeypatch):
    monkeypatch.setattr(
        "services.trading_clock.TradingClock.is_in_trading_session",
        classmethod(lambda cls: True)
    )
    r = client.delete(
        "/api/orders/99999999?trd_date=20260614",  # v6: order_no
        headers=_auth(_trader_token(active_day)),
    )
    assert r.status_code == 404


# ──── 查询 ────

def test_list_orders_with_filter(client, active_day):
    db = SessionLocal()
    for i in range(3):
        db.add(Order(
            trd_date="20260614",
            order_id=f"OID-{i}", user_def=f"CID-{i}", order_no=f"1000000{i}",
            stock_code="600030.SH" if i < 2 else "000001.SZ",
            order_type="23", price_type=11, price=12.5, volume=100,
            status="49" if i == 0 else "51",
        ))
    db.commit()
    db.close()
    headers = _auth(_trader_token(active_day))

    r = client.get("/api/orders", headers=headers)
    assert r.status_code == 200
    assert r.json()["code"] == 0
    assert len(r.json()["list"]) == 3

    r2 = client.get("/api/orders?stock_code=600030.SH", headers=headers)
    assert len(r2.json()["list"]) == 2

    r3 = client.get("/api/orders?status=49", headers=headers)
    assert len(r3.json()["list"]) == 1

    r4 = client.get("/api/orders?trd_date=20260613", headers=headers)
    assert len(r4.json()["list"]) == 0


def test_list_orders_default_trd_date_uses_active(client, active_day):
    """未传 trd_date → 用激活日"""
    db = SessionLocal()
    db.add(Order(
        trd_date="20260614",
        order_id="OID-A", user_def="CID-A", order_no="10000099",
        stock_code="600030.SH", order_type="23", price_type=11, price=12.5, volume=100,
    ))
    db.commit()
    db.close()
    r = client.get("/api/orders", headers=_auth(_trader_token(active_day)))
    assert len(r.json()["list"]) == 1
    assert r.json()["list"][0]["trd_date"] == "20260614"
