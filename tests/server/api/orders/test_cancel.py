"""
test_cancel.py — v7 DELETE /api/orders/{order_no} 验证

覆盖：
- 撤单成功 → 不本地改 status
- 撤单失败 → 500
- 撤单时 broker order_id 还没回报 → BROKER_NOT_READY
- 撤单 RPC 失败 → status=55 无 trade 落库
- 撤单 ACK 非 0 → status=55 无 trade 落库
- 撤单插入 trade row with type=1
- status 不可撤时跳过 trade 插入
- 全成撤单 → 不插 cancel trade
"""
import pytest
from datetime import datetime, time, timedelta
from unittest.mock import patch, MagicMock

from fastapi import HTTPException
from fastapi.testclient import TestClient

from server.db import Base, engine, SessionLocal, init_db, get_db
from server.models.orm import Order, SysStatus, TradingSession

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
    from server.main import app
    return TestClient(app)

@pytest.fixture
def active_day(fresh_db):
    """fixture: 激活 20260614 + Trader user（依赖 fresh_db 自动 drop_all）"""
    from server.models.user import User
    from server.auth.security import hash_password
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
    from server.auth.security import create_access_token
    return create_access_token({"sub": str(user_id), "role": "trader"})

def _auth(t: str) -> dict:
    return {"Authorization": f"Bearer {t}"}

# ──── 屏障：未做日初 → 拒绝 ────

@pytest.fixture
def no_active_day(fresh_db):
    from server.models.user import User
    from server.auth.security import hash_password
    db = SessionLocal()
    db.query(User).filter_by(username="trader1").delete()
    db.commit()
    trader = User(username="trader1", password_hash=hash_password("x"), role="trader")
    db.add(trader)
    db.commit()
    db.refresh(trader)
    db.close()
    return trader.id
def test_cancel_calls_rpc_inserts_local_cancel_row(client, active_day, monkeypatch):
    """v9: DELETE 插 cancel-row (order_flag=1, status=53) + 调 RPC,原单 status 不本地改"""
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
    mock_ws = AsyncMock()
    monkeypatch.setattr("api.orders.ws_manager.broadcast", mock_ws)

    r = client.delete(
        "/api/orders/10000010?trd_date=20260614",
        headers=_auth(_trader_token(active_day)),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    # RPC 用查到的 broker order_id
    call_kwargs = mock_rpc.await_args.kwargs
    assert call_kwargs["order_id"] == "OID-X"
    # v9: cancel-row 存在 + 字段
    assert body["cancel_order"] is not None
    co = body["cancel_order"]
    assert co["order_flag"] == 1
    assert co["status"] == "53"
    assert co["volume"] == 0
    assert co["user_def"] == "CANCEL:10000010"
    assert co["stock_code"] == "600030.SH"
    assert co["price"] == 12.5
    # 原单 status 仍 49(等 push 改)
    db = SessionLocal()
    row = db.query(Order).filter_by(order_no="10000010", trd_date="20260614").first()
    assert row.status == "49"
    db.close()
    # WS broadcast 被调
    assert mock_ws.await_count == 1
    payload = mock_ws.await_args.args[1]
    assert payload["order_flag"] == 1
    assert payload["status"] == "53"

def test_cancel_broker_not_ready_returns_business_error(client, active_day, monkeypatch):
    """v6: 撤单时 broker order_id 还没回报 → BROKER_NOT_READY,不调 RPC,不插 cancel-row"""
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
    assert body["cancel_order"] is None
    assert mock_rpc.await_count == 0  # RPC 不会被调
    # 没有 cancel-row 落库
    db = SessionLocal()
    cancel_rows = db.query(Order).filter(Order.user_def == "CANCEL:10000011").all()
    assert len(cancel_rows) == 0
    db.close()

def test_cancel_rpc_fail_sets_status_55_no_trade(client, active_day, monkeypatch):
    """v9: RPC 抛异常 → 仍 200,cancel-row.status=55,无 cancel-trade"""
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
    mock_ws = AsyncMock()
    monkeypatch.setattr("api.orders.ws_manager.broadcast", mock_ws)

    r = client.delete(
        "/api/orders/10000020?trd_date=20260614",
        headers=_auth(_trader_token(active_day)),
    )
    # v9: 不再 500,返 200 + 业务码 1
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 1
    assert body["cancel_order"]["status"] == "55"  # 废单保留
    assert body["error"] is not None
    # 无 cancel-trade
    from server.models.orm import Trade
    db = SessionLocal()
    cancel_trades = db.query(Trade).filter(Trade.trade_type == 1).all()
    assert len(cancel_trades) == 0
    db.close()
    # WS 仍 broadcast
    assert mock_ws.await_count == 1
    payload = mock_ws.await_args.args[1]
    assert payload["status"] == "55"

def test_cancel_ack_nonzero_sets_status_55_no_trade(client, active_day, monkeypatch):
    """v9: ack.code != 0 → cancel-row.status=55,无 cancel-trade"""
    monkeypatch.setattr(
        "services.trading_clock.TradingClock.is_in_trading_session",
        classmethod(lambda cls: True)
    )
    db = SessionLocal()
    db.add(Order(
        trd_date="20260614",
        order_id="OID-Z", user_def="CID-Z", order_no="10000030",
        stock_code="600030.SH", order_type="23", price_type=11, price=12.5, volume=100,
        status="49",
    ))
    db.commit()
    db.close()

    mock_rpc = AsyncMock(return_value={"code": 1, "msg": "柜台拒单", "list": []})
    monkeypatch.setattr("api.orders.rpc_cancel_order", mock_rpc)

    r = client.delete(
        "/api/orders/10000030?trd_date=20260614",
        headers=_auth(_trader_token(active_day)),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 1
    assert body["cancel_order"]["status"] == "55"
    assert body["cancel_order"]["status_msg"] == "柜台拒单"
    from server.models.orm import Trade
    db = SessionLocal()
    assert db.query(Trade).filter(Trade.trade_type == 1).count() == 0
    db.close()

def test_cancel_not_found_returns_404(client, active_day, monkeypatch):
    monkeypatch.setattr(
        "services.trading_clock.TradingClock.is_in_trading_session",
        classmethod(lambda cls: True)
    )
    r = client.delete(
        "/api/orders/99999999?trd_date=20260614",
        headers=_auth(_trader_token(active_day)),
    )
    assert r.status_code == 404

def test_cancel_inserts_trade_row_with_type_1(client, active_day, monkeypatch):
    """v9: RPC 成功时,同步插 trade_type=1 行(剩余可撤量)"""
    monkeypatch.setattr(
        "services.trading_clock.TradingClock.is_in_trading_session",
        classmethod(lambda cls: True)
    )
    from server.models.orm import Trade
    db = SessionLocal()
    db.add(Order(
        trd_date="20260614",
        order_id="OID-P", user_def="CID-P", order_no="10000040",
        stock_code="600030.SH", order_type="23", price_type=11, price=12.5, volume=100,
        status="49", traded_volume=30, traded_amount=375.0, avg_price=12.5,
    ))
    db.commit()
    db.close()

    mock_rpc = AsyncMock(return_value={"code": 0, "msg": "ok", "list": []})
    monkeypatch.setattr("api.orders.rpc_cancel_order", mock_rpc)
    mock_ws = AsyncMock()
    monkeypatch.setattr("api.orders.ws_manager.broadcast", mock_ws)

    r = client.delete(
        "/api/orders/10000040?trd_date=20260614",
        headers=_auth(_trader_token(active_day)),
    )
    assert r.status_code == 200
    body = r.json()
    cancel_order_no = body["cancel_order"]["order_no"]
    # trade 行
    db = SessionLocal()
    trade = db.query(Trade).filter_by(trade_type=1, order_no=cancel_order_no).first()
    assert trade is not None
    assert trade.volume == 70  # = orig.volume - orig.traded_volume
    assert trade.price == 12.5  # avg_price
    assert trade.amount == 12.5 * 70
    assert trade.trade_id.startswith("CANCEL-")
    db.close()
    # trade_update 也 broadcast
    assert mock_ws.await_count == 2
    trade_payload = mock_ws.await_args_list[1].args[1]
    assert trade_payload["trade_type"] == 1
    assert trade_payload["volume"] == 70

def test_cancel_no_insert_when_status_not_cancellable(client, active_day, monkeypatch):
    """v9: orig.status=51(已成) → 不插 cancel-row,直接返"""
    monkeypatch.setattr(
        "services.trading_clock.TradingClock.is_in_trading_session",
        classmethod(lambda cls: True)
    )
    db = SessionLocal()
    db.add(Order(
        trd_date="20260614",
        order_id="OID-DONE", user_def="", order_no="10000050",
        stock_code="600030.SH", order_type="23", price_type=11, price=12.5, volume=100,
        status="51",  # 已成
    ))
    db.commit()
    db.close()

    mock_rpc = AsyncMock(return_value={"code": 0, "msg": "ok", "list": []})
    monkeypatch.setattr("api.orders.rpc_cancel_order", mock_rpc)

    r = client.delete(
        "/api/orders/10000050?trd_date=20260614",
        headers=_auth(_trader_token(active_day)),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 1
    assert body["cancel_order"] is None
    assert mock_rpc.await_count == 0
    # 无 cancel-row 落库
    db = SessionLocal()
    assert db.query(Order).filter(Order.user_def.like("CANCEL:10000050%")).count() == 0
    db.close()

def test_cancel_rpc_success_flattens_orig_cancelled_volume(client, active_day, monkeypatch):
    """change system-delegation-price-fill-calc: R1
    DELETE 端点 broker ack.code == 0 → 原委托 cancelled_volume 一次性抹平到 volume
    """
    monkeypatch.setattr(
        "services.trading_clock.TradingClock.is_in_trading_session",
        classmethod(lambda cls: True)
    )
    db = SessionLocal()
    db.add(Order(
        trd_date="20260614",
        order_id="OID-R1", user_def="CID-R1", order_no="10000020",
        stock_code="600030.SH", order_type="23", price_type=11, price=12.5, volume=100,
        status="49", traded_volume=30, traded_amount=375.0,
        cancelled_volume=0,
    ))
    db.commit()
    db.close()

    mock_rpc = AsyncMock(return_value={"code": 0, "msg": "ok", "list": []})
    monkeypatch.setattr("api.orders.rpc_cancel_order", mock_rpc)
    mock_ws = AsyncMock()
    monkeypatch.setattr("api.orders.ws_manager.broadcast", mock_ws)

    r = client.delete(
        "/api/orders/10000020?trd_date=20260614",
        headers=_auth(_trader_token(active_day)),
    )
    assert r.status_code == 200
    assert r.json()["code"] == 0

    # 原委托 R1: cancelled_volume = volume
    db = SessionLocal()
    orig = db.query(Order).filter_by(order_no="10000020", trd_date="20260614").first()
    db.close()
    assert orig.cancelled_volume == 100  # R1 抹平
    assert orig.volume == 100
    assert orig.cancelled_volume == orig.volume


def test_cancel_rpc_fail_keeps_orig_cancelled_volume(client, active_day, monkeypatch):
    """change system-delegation-price-fill-calc: R4
    DELETE 端点 broker ack.code != 0 → 原委托 cancelled_volume 不动，仅 cancel-row 自身写 status=55
    """
    monkeypatch.setattr(
        "services.trading_clock.TradingClock.is_in_trading_session",
        classmethod(lambda cls: True)
    )
    db = SessionLocal()
    db.add(Order(
        trd_date="20260614",
        order_id="OID-R4", user_def="CID-R4", order_no="10000021",
        stock_code="600030.SH", order_type="23", price_type=11, price=12.5, volume=100,
        status="49", traded_volume=10, traded_amount=125.0,
        cancelled_volume=20,  # 已有部分撤单
    ))
    db.commit()
    db.close()

    mock_rpc = AsyncMock(return_value={"code": 1, "msg": "柜台拒撤", "list": []})
    monkeypatch.setattr("api.orders.rpc_cancel_order", mock_rpc)

    r = client.delete(
        "/api/orders/10000021?trd_date=20260614",
        headers=_auth(_trader_token(active_day)),
    )
    assert r.status_code == 200
    assert r.json()["code"] == 1

    # 原委托 R4: cancelled_volume 仍 20 (不动)
    db = SessionLocal()
    orig = db.query(Order).filter_by(order_no="10000021", trd_date="20260614").first()
    db.close()
    assert orig.cancelled_volume == 20  # R4 不动
    # cancel-row 自身写 55
    co = db.query(Order).filter_by(order_no=orig.order_no, trd_date="20260614").filter(Order.order_flag == 1).first()
    # co 已经在前面 refresh 关闭后再开 (上面已经 db.close)，重新查
    db = SessionLocal()
    co = db.query(Order).filter(Order.user_def == "CANCEL:10000021").first()
    db.close()
    assert co is not None
    assert co.status == "55"  # cancel-row 自身废单


def test_cancel_full_trade_no_cancel_trade_inserted(client, active_day, monkeypatch):
    """v9: orig.traded_volume=orig.volume(完全成交)→ cancelled_qty=0,无 cancel-trade"""
    monkeypatch.setattr(
        "services.trading_clock.TradingClock.is_in_trading_session",
        classmethod(lambda cls: True)
    )
    from server.models.orm import Trade
    db = SessionLocal()
    db.add(Order(
        trd_date="20260614",
        order_id="OID-FULL", user_def="", order_no="10000060",
        stock_code="600030.SH", order_type="23", price_type=11, price=12.5, volume=100,
        status="49", traded_volume=100, traded_amount=1250.0, avg_price=12.5,
    ))
    db.commit()
    db.close()

    mock_rpc = AsyncMock(return_value={"code": 0, "msg": "ok", "list": []})
    monkeypatch.setattr("api.orders.rpc_cancel_order", mock_rpc)

    r = client.delete(
        "/api/orders/10000060?trd_date=20260614",
        headers=_auth(_trader_token(active_day)),
    )
    # 完全成交时 status=49(已报)但 traded=volume 仍可撤(pre-check 不会拦)
    # 实际 broker 会拒(status=51);这里测本地逻辑
    assert r.status_code == 200
    body = r.json()
    if body["code"] == 0:
        # 走通路径: cancel-row 在,但 trade 不在
        cancel_order_no = body["cancel_order"]["order_no"]
        db = SessionLocal()
        assert db.query(Trade).filter(Trade.trade_type == 1, Trade.order_no == cancel_order_no).count() == 0
        db.close()
    else:
        # pre-check 拦了,正常
        assert body["cancel_order"] is None

# ──── 查询 ────
