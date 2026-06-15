"""
test_orders_api.py — 验证 v5 下单/撤单/查询（schema refactor）

mock RPC + TradingClock，覆盖：
- 幂等（同 client_order_id 二次提交返原单）
- 屏障（未激活 / 非时段拒绝）
- 下单成功 → status=49
- 下单失败 → status=55 废单
- 撤单成功 → 不本地改 status
- 撤单失败 → 500
- 查询 DB

v5 改动：
- 移除 order_remark 字段（v4 错误复用 broker 透传字段）
- TRD_DATE → trd_date
- TradingDay → SysStatus
- 复合主键 (trd_date, order_id)
- DELETE /{order_id} 需要 trd_date 参数（复合主键定位）
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))

import pytest
from datetime import datetime, time, timedelta
from unittest.mock import AsyncMock, patch, MagicMock

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
            "client_order_id": "CID1",
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
        json={"client_order_id": "CID1", "stock_code": "600030.SH",
              "order_type": "23", "volume": 100, "price": 12.5, "price_type": 11},
        headers=_auth(_trader_token(active_day)),
    )
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "OUTSIDE_TRADING_SESSION"


# ──── 幂等 ────

def test_place_idempotent_returns_existing(client, active_day, monkeypatch):
    monkeypatch.setattr(
        "services.trading_clock.TradingClock.is_in_trading_session",
        classmethod(lambda cls: True)
    )
    mock_rpc = AsyncMock(return_value={"code": 0, "msg": "ok", "list": [{"order_id": "OID1"}]})
    monkeypatch.setattr("api.orders.ord_stk", mock_rpc)
    headers = _auth(_trader_token(active_day))
    body = {
        "client_order_id": "CID-IDEM",
        "stock_code": "600030.SH",
        "order_type": "23",
        "volume": 100,
        "price": 12.5,
        "price_type": 11,
    }
    r1 = client.post("/api/orders/place", json=body, headers=headers)
    assert r1.status_code == 200
    order_id_1 = r1.json()["order"]["order_id"]

    r2 = client.post("/api/orders/place", json=body, headers=headers)
    assert r2.status_code == 200
    assert r2.json()["order"]["order_id"] == order_id_1

    # 只能调一次 RPC（第二次幂等不调）
    assert mock_rpc.await_count == 1


# ──── 下单成功 → status=49 ────

def test_place_success_writes_local_and_calls_rpc(client, active_day, monkeypatch):
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
        json={"client_order_id": "CID-OK", "stock_code": "600030.SH",
              "order_type": "23", "volume": 100, "price": 12.5, "price_type": 11},
        headers=_auth(_trader_token(active_day)),
    )
    assert r.status_code == 200
    body = r.json()["order"]
    assert body["status"] == "49"
    assert body["order_id"] == "BROKER-OID-1"
    assert body["order_no"] == "10000001"  # 第一次生成
    assert "order_remark" not in body  # v5 字段已移除
    assert body["trd_date"] == "20260614"
    assert mock_rpc.await_count == 1
    # 校验传给柜台的 remark
    call_kwargs = mock_rpc.await_args.kwargs
    assert call_kwargs["remark"] == "10000001"
    # 推 WS
    assert mock_ws.await_count == 1


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
        json={"client_order_id": "CID-FAIL", "stock_code": "600030.SH",
              "order_type": "23", "volume": 100, "price": 12.5, "price_type": 11},
        headers=_auth(_trader_token(active_day)),
    )
    assert r.status_code == 200
    body = r.json()["order"]
    assert body["status"] == "55"
    assert "RPC 失败" in body["status_msg"]


# ──── 撤单：调 RPC，不本地改 status ────

def test_cancel_calls_rpc_does_not_change_status(client, active_day, monkeypatch):
    monkeypatch.setattr(
        "services.trading_clock.TradingClock.is_in_trading_session",
        classmethod(lambda cls: True)
    )
    db = SessionLocal()
    db.add(Order(
        trd_date="20260614",
        order_id="OID-X", client_order_id="CID-X", order_no="10000010",
        stock_code="600030.SH", order_type="23", price_type=11, price=12.5, volume=100,
        status="49",
    ))
    db.commit()
    db.close()

    mock_rpc = AsyncMock(return_value={"code": 0, "msg": "ok", "list": []})
    monkeypatch.setattr("api.orders.cancel_order", mock_rpc)

    # v5: 复合主键需 trd_date
    r = client.delete(
        "/api/orders/OID-X?trd_date=20260614",
        headers=_auth(_trader_token(active_day)),
    )
    assert r.status_code == 200
    # 状态没改（等 push）
    db = SessionLocal()
    row = db.query(Order).filter_by(order_id="OID-X", trd_date="20260614").first()
    assert row.status == "49"
    db.close()


def test_cancel_rpc_fail_returns_500(client, active_day, monkeypatch):
    monkeypatch.setattr(
        "services.trading_clock.TradingClock.is_in_trading_session",
        classmethod(lambda cls: True)
    )
    db = SessionLocal()
    db.add(Order(
        trd_date="20260614",
        order_id="OID-Y", client_order_id="CID-Y", order_no="10000020",
        stock_code="600030.SH", order_type="23", price_type=11, price=12.5, volume=100,
        status="49",
    ))
    db.commit()
    db.close()

    mock_rpc = AsyncMock(side_effect=Exception("rpc 断连"))
    monkeypatch.setattr("api.orders.cancel_order", mock_rpc)

    r = client.delete(
        "/api/orders/OID-Y?trd_date=20260614",
        headers=_auth(_trader_token(active_day)),
    )
    assert r.status_code == 500


def test_cancel_not_found_returns_404(client, active_day, monkeypatch):
    monkeypatch.setattr(
        "services.trading_clock.TradingClock.is_in_trading_session",
        classmethod(lambda cls: True)
    )
    r = client.delete(
        "/api/orders/NOT-EXIST?trd_date=20260614",
        headers=_auth(_trader_token(active_day)),
    )
    assert r.status_code == 404


# ──── 查询 ────

def test_list_orders_with_filter(client, active_day):
    db = SessionLocal()
    for i in range(3):
        db.add(Order(
            trd_date="20260614",
            order_id=f"OID-{i}", client_order_id=f"CID-{i}", order_no=f"1000000{i}",
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
        order_id="OID-A", client_order_id="CID-A", order_no="10000099",
        stock_code="600030.SH", order_type="23", price_type=11, price=12.5, volume=100,
    ))
    db.commit()
    db.close()
    r = client.get("/api/orders", headers=_auth(_trader_token(active_day)))
    assert len(r.json()["list"]) == 1
    assert r.json()["list"][0]["trd_date"] == "20260614"
