"""
test_place.py — v7/v8 POST /api/orders/place 验证

覆盖：
- 屏障：未激活交易日 / 非交易时段 → 拒绝
- 下单成功 → status=49,broker 带回 order_id 时写入
- 下单成功 → broker 不带回 order_id 时 order_id 为空
- 下单失败 → status=55 废单
- v8: POST /place 响应有 list 字段（统一 RPC 格式）
- v8: POST /place 推 WS 时 payload 必带 trd_date + order_no
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

def test_place_rpc_fail_logs_exception(client, active_day, monkeypatch, caplog):
    """RPC 抛异常时记 log.exception（含 stack trace）— 2ccac60。

    之前: bare except 吃掉异常，broker 断连时只在 status_msg 里看到一行字。
    之后: log.exception 带 traceback，便于排查 broker / 网络 / 序列化问题。
    """
    import logging
    monkeypatch.setattr(
        "services.trading_clock.TradingClock.is_in_trading_session",
        classmethod(lambda cls: True)
    )
    mock_rpc = AsyncMock(side_effect=Exception("柜台断连"))
    monkeypatch.setattr("api.orders.ord_stk", mock_rpc)

    with caplog.at_level(logging.ERROR, logger="api.orders"):
        r = client.post(
            "/api/orders/place",
            json={"user_def": "CID-FAIL-LOG", "stock_code": "600030.SH",
                  "order_type": "23", "volume": 100, "price": 12.5, "price_type": 11},
            headers=_auth(_trader_token(active_day)),
        )

    assert r.status_code == 200
    # log.exception 会附 exc_info（traceback）→ r.exc_info is not None
    exc_records = [r for r in caplog.records if r.exc_info is not None]
    assert exc_records, (
        f"expected log.exception with traceback, got: "
        f"{[(r.levelname, r.getMessage()) for r in caplog.records]}"
    )


def test_place_rpc_ack_fail_marks_rejected_and_flattens_cancelled(client, active_day, monkeypatch):
    """change system-delegation-price-fill-calc: R2a 本地拒单
    broker ack.code != 0 时 order.status = "55" 且 cancelled_volume = volume
    """
    monkeypatch.setattr(
        "services.trading_clock.TradingClock.is_in_trading_session",
        classmethod(lambda cls: True)
    )
    mock_rpc = AsyncMock(return_value={"code": 1, "msg": "资金不足", "list": []})
    monkeypatch.setattr("api.orders.ord_stk", mock_rpc)

    r = client.post(
        "/api/orders/place",
        json={"user_def": "CID-REJECT", "stock_code": "600030.SH",
              "order_type": "23", "volume": 100, "price": 12.5, "price_type": 11},
        headers=_auth(_trader_token(active_day)),
    )
    assert r.status_code == 200
    body = r.json()["order"]
    assert body["status"] == "55"
    assert body["cancelled_volume"] == 100  # R2a 抹平 == volume

    # DB 验证
    from server.db import SessionLocal
    db = SessionLocal()
    o = db.query(Order).filter_by(user_def="CID-REJECT").first()
    db.close()
    assert o is not None
    assert o.cancelled_volume == o.volume
    assert o.volume == 100

# ──── 撤单(v6:用 order_no) ────
def test_place_response_has_list_field_with_one_order(client, active_day, monkeypatch):
    """v8: POST /place 响应有 list 字段,内容是 1 个 OrderOut(冗余但统一)
    前端 axios 拦截器解包后 res.data = list[0]
    """
    monkeypatch.setattr(
        "services.trading_clock.TradingClock.is_in_trading_session",
        classmethod(lambda cls: True)
    )
    mock_rpc = AsyncMock(return_value={"code": 0, "msg": "ok", "list": [{"order_id": "BROKER-OID-LIST"}]})
    monkeypatch.setattr("api.orders.ord_stk", mock_rpc)
    monkeypatch.setattr("api.orders.ws_manager.broadcast", AsyncMock())

    r = client.post(
        "/api/orders/place",
        json={"user_def": "CID-LIST", "stock_code": "600030.SH",
              "order_type": "23", "volume": 100, "price": 12.5, "price_type": 11},
        headers=_auth(_trader_token(active_day)),
    )
    assert r.status_code == 200
    body = r.json()
    # 旧字段保留(向后兼容)
    assert body["order"]["order_no"] == "10000001"
    # 新字段:list 含 1 个 OrderOut,内容跟 order 一致
    assert "list" in body
    assert isinstance(body["list"], list)
    assert len(body["list"]) == 1
    o = body["list"][0]
    assert o["order_no"] == "10000001"
    assert o["stock_code"] == "600030.SH"
    assert o["status"] == "49"
    assert o["order_id"] == "BROKER-OID-LIST"
    assert o["trd_date"] == "20260614"

def test_place_response_list_field_on_rpc_fail(client, active_day, monkeypatch):
    """v8: 柜台 RPC 失败时,list 字段也要返(里面是 55 废单)"""
    monkeypatch.setattr(
        "services.trading_clock.TradingClock.is_in_trading_session",
        classmethod(lambda cls: True)
    )
    mock_rpc = AsyncMock(side_effect=Exception("柜台断"))
    monkeypatch.setattr("api.orders.ord_stk", mock_rpc)

    r = client.post(
        "/api/orders/place",
        json={"user_def": "CID-FAIL-LIST", "stock_code": "600030.SH",
              "order_type": "23", "volume": 100, "price": 12.5, "price_type": 11},
        headers=_auth(_trader_token(active_day)),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 1
    assert len(body["list"]) == 1
    assert body["list"][0]["status"] == "55"
    # 旧字段仍可用
    assert body["order"]["status"] == "55"

def test_place_response_ws_payload_has_trd_date_and_order_no(client, active_day, monkeypatch):
    """v8: POST /place 推 WS 时,payload 必带 trd_date + order_no(前端推送守门)"""
    monkeypatch.setattr(
        "services.trading_clock.TradingClock.is_in_trading_session",
        classmethod(lambda cls: True)
    )
    mock_rpc = AsyncMock(return_value={"code": 0, "msg": "ok", "list": [{"order_id": "OID-WS"}]})
    monkeypatch.setattr("api.orders.ord_stk", mock_rpc)
    mock_ws = AsyncMock()
    monkeypatch.setattr("api.orders.ws_manager.broadcast", mock_ws)

    client.post(
        "/api/orders/place",
        json={"user_def": "CID-WS", "stock_code": "600030.SH",
              "order_type": "23", "volume": 100, "price": 12.5, "price_type": 11},
        headers=_auth(_trader_token(active_day)),
    )

    # 检查 broadcast 调用:order_update channel
    call_args = mock_ws.await_args
    payload = call_args.args[1]  # broadcast(channel, payload)
    assert payload["trd_date"] == "20260614"
    assert payload["order_no"] == "10000001"
    assert payload["remark"] == "10000001"  # broker 透传字段
    assert payload["order_id"] == "OID-WS"  # broker 带回
    assert payload["status"] == "49"
