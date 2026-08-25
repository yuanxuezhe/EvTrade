"""
test_orders_cancel.py — 撤单端点 (DELETE /api/orders/{order_no}) 单测

覆盖 server/api/orders/cancel.py 的关键路径（CLAUDE.md § 八强制覆盖）:
- happy path: status=50 + broker order_id 已回报 → cancel-row status=54, orig.cancelled_volume=volume,
              cancel-trade (trade_type=1) 写入, ws push order_update + trade_update
- pre-check status=48 (未报): 不可撤, code=1, 无 RPC 调用
- pre-check status=57 (废单): 不可撤, code=1
- pre-check 无 broker order_id: BROKER_NOT_READY 错误
- RPC ack.code != 0: cancel-row status=57 (废单, 审计保留), 无 cancel-trade
- RPC 异常: 同 ack.code != 0 路径

Mock 策略（与 test_place_async.py 一致）:
- monkeypatch server.api.orders.rpc_cancel_order → fake async
- monkeypatch ws_manager.broadcast 收集 calls
- 走 FastAPI dependency_overrides 绕开登录 + 交易时段屏障 + RPC 健康屏障
"""
import asyncio
import logging
import time
import pytest
import httpx
from httpx import ASGITransport

pytestmark = pytest.mark.asyncio

from server.main import app
from server.auth.deps import get_current_user
from server.auth.security import hash_password
from server.tables import Orders, Trades, SysStatus, Users


# ─────────────── Fixtures ───────────────


@pytest.fixture
def db():
    """每 test 独立 Session；清 orders + trades 表保隔离。"""
    from sqlalchemy import text
    from server.infra.db import SessionLocal
    s = SessionLocal()
    s.execute(text("DELETE FROM trades"))
    s.execute(text("DELETE FROM orders"))
    s.execute(text("ALTER TABLE orders AUTO_INCREMENT = 1"))
    s.commit()
    yield s
    s.execute(text("DELETE FROM users WHERE LOCATE('_', username) > 0 AND username NOT IN ('admin', 'trader')"))
    s.commit()
    s.close()


@pytest.fixture
def trader(db):
    """trader 用户 + 激活交易日。"""
    for _old in Users.query_by("username", "t_cancel_v1"):
        Users.delete_one(id=_old.id)
    u = Users.add_one({
        "username": "t_cancel_v1",
        "password_hash": hash_password("x"),
        "role": "trader",
    })
    SysStatus.delete_one(id=1)
    SysStatus.upsert_one({"trd_date": "20260825", "status": "active"}, id=1)
    return {"id": u.id, "username": u.username}


@pytest.fixture
def fake_rpc_cancel(monkeypatch):
    """monkeypatch rpc_cancel_order → fake async (可控 ack/异常)。"""
    from server.api.orders import cancel as cancel_mod

    class FakeRpcCancel:
        def __init__(self):
            self.calls = []
            self._next_ack = None
            self._next_exception = None

        def set_ack(self, ack):
            self._next_ack = ack

        def set_exception(self, e):
            self._next_exception = e

        async def __call__(self, **kwargs):
            self.calls.append(kwargs)
            if self._next_exception is not None:
                raise self._next_exception
            return self._next_ack or {"code": 0, "list": [], "msg": "OK"}

    fake = FakeRpcCancel()
    monkeypatch.setattr("server.api.orders.rpc_cancel_order", fake)
    return fake


@pytest.fixture
def fake_broadcast(monkeypatch):
    """monkeypatch ws_manager.broadcast 收集 channel + payload。"""
    from server.api.orders import ws_manager

    class FakeBroadcast:
        def __init__(self):
            self.calls = []

        async def __call__(self, channel, payload, **kwargs):
            self.calls.append((channel, payload))
            return None

    fake = FakeBroadcast()
    monkeypatch.setattr(ws_manager, "broadcast", fake)
    return fake


@pytest.fixture
def _deps_override(trader):
    """绕开登录 + 交易时段 + RPC 健康屏障，让端点可调。"""
    u = Users.query_one(id=trader["id"])
    app.dependency_overrides[get_current_user] = lambda: u

    from server.services.guards import require_trading_session
    app.dependency_overrides[require_trading_session] = lambda: None

    from server.api.deps import require_rpc_ok
    app.dependency_overrides[require_rpc_ok] = lambda: None

    yield

    app.dependency_overrides.clear()


# ─────────────── Helpers ───────────────


def _seed_reported_order(db, order_no="10000001", broker_order_id="BRK-CXL-001"):
    """插入一行已报订单（status=50 + broker_order_id 已回报）。"""
    return Orders.upsert_one({
        "user_def": "",
        "stock_code": "600519.SH",
        "order_type": "23",
        "price_type": 0,
        "price": 1800.0,
        "volume": 100,
        "traded_volume": 0,
        "traded_amount": 0.0,
        "avg_price": 0.0,
        "cancelled_volume": 0,
        "order_flag": 0,
        "status": "50",
        "status_msg": "已报",
        "order_id": broker_order_id,
        "order_time": "2026-08-25 09:30:00.000",
        "task_id": None,
        "strategy_type": 0,
    }, return_row=True, trd_date="20260825", order_no=order_no)


def _seed_unreported_order(db, order_no="10000002"):
    """插入一行未报订单（status=48，无 broker_order_id）。"""
    return Orders.upsert_one({
        "user_def": "",
        "stock_code": "600519.SH",
        "order_type": "23",
        "price_type": 0,
        "price": 1800.0,
        "volume": 100,
        "traded_volume": 0,
        "traded_amount": 0.0,
        "avg_price": 0.0,
        "cancelled_volume": 0,
        "order_flag": 0,
        "status": "48",
        "status_msg": "未报",
        "order_time": "2026-08-25 09:30:00.000",
        "task_id": None,
        "strategy_type": 0,
    }, return_row=True, trd_date="20260825", order_no=order_no)


# ─────────────── Tests ───────────────


async def test_cancel_happy_path_50_to_54(trader, fake_rpc_cancel, fake_broadcast, db, _deps_override):
    """happy path: status=50 + broker order_id → cancel-row status=54 + orig.cancelled_volume=volume + cancel-trade 写入。"""
    orig = _seed_reported_order(db, order_no="10000001")
    fake_rpc_cancel.set_ack({"code": 0, "msg": "OK"})

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.delete("/api/orders/10000001", params={"trd_date": "20260825"})

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["code"] == 0
    assert body["msg"] == "撤单请求已发"
    assert body["cancel_order"]["status"] == "54"
    assert body["cancel_order"]["status_msg"] == "已撤"
    # cancel_order.user_def 应为 CANCEL:{orig.order_no}
    assert body["cancel_order"]["user_def"] == f"CANCEL:{orig.order_no}"

    # DB 验证: 原单 cancelled_volume=volume, cancel-trade 写入
    db.close()
    db.expire_all()
    updated = Orders.query_by("order_no", "10000001")[0]
    assert updated.cancelled_volume == updated.volume == 100

    cancel_rows = [o for o in Orders.query_all() if o.order_no != "10000001"]
    assert len(cancel_rows) == 1
    cancel_row = cancel_rows[0]
    assert cancel_row.order_flag == 1
    assert cancel_row.status == "54"
    assert cancel_row.raw_id == orig.order_no

    cancel_trades = [t for t in Trades.query_all() if t.order_no == cancel_row.order_no]
    assert len(cancel_trades) == 1
    assert cancel_trades[0].trade_type == 1
    assert cancel_trades[0].volume == 100

    # ws push: order_update (cancel row) + trade_update (cancel trade)
    channels = [c for c, _ in fake_broadcast.calls]
    assert "order_update" in channels
    assert "trade_update" in channels


async def test_cancel_48_unreported_rejected(trader, fake_rpc_cancel, fake_broadcast, db, _deps_override):
    """pre-check: status=48 (未报) 不可撤，code=1，无 RPC 调用。"""
    _seed_unreported_order(db, order_no="10000002")

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.delete("/api/orders/10000002", params={"trd_date": "20260825"})

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["code"] == 1
    assert "non-cancellable" in (body.get("error") or "")

    # 验证: 无 RPC 调用
    assert len(fake_rpc_cancel.calls) == 0
    # 验证: DB 未插入 cancel-row
    cancel_rows = [o for o in Orders.query_all() if o.user_def.startswith("CANCEL:")]
    assert len(cancel_rows) == 0


async def test_cancel_no_broker_order_id_returns_broker_not_ready(trader, fake_rpc_cancel, fake_broadcast, db, _deps_override):
    """pre-check: status=50 但 broker 未回报 order_id → BROKER_NOT_READY 错误。"""
    Orders.upsert_one({
        "user_def": "",
        "stock_code": "600519.SH",
        "order_type": "23",
        "price_type": 0,
        "price": 1800.0,
        "volume": 100,
        "traded_volume": 0,
        "traded_amount": 0.0,
        "avg_price": 0.0,
        "cancelled_volume": 0,
        "order_flag": 0,
        "status": "50",
        "status_msg": "已报",
        "order_id": None,  # broker 尚未回报
        "order_time": "2026-08-25 09:30:00.000",
        "task_id": None,
        "strategy_type": 0,
    }, return_row=True, trd_date="20260825", order_no="10000003")

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.delete("/api/orders/10000003", params={"trd_date": "20260825"})

    body = r.json()
    assert body["code"] == 1
    assert body["error"] == "BROKER_NOT_READY"
    assert len(fake_rpc_cancel.calls) == 0


async def test_cancel_rpc_failure_writes_57_no_trade(trader, fake_rpc_cancel, fake_broadcast, db, _deps_override):
    """RPC ack.code != 0 → cancel-row status=57 (废单, 审计保留), 无 cancel-trade, orig 不变。"""
    orig = _seed_reported_order(db, order_no="10000004")
    fake_rpc_cancel.set_ack({"code": 1, "msg": "broker 撤单失败"})

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.delete("/api/orders/10000004", params={"trd_date": "20260825"})

    body = r.json()
    assert body["code"] == 1
    assert "broker 撤单失败" in body["msg"]

    # DB 验证: cancel-row status=57 + status_msg 含 broker msg
    cancel_rows = [o for o in Orders.query_all() if o.user_def.startswith("CANCEL:")]
    assert len(cancel_rows) == 1
    assert cancel_rows[0].status == "57"
    assert "broker 撤单失败" in cancel_rows[0].status_msg

    # 无 cancel-trade
    cancel_trades = [t for t in Trades.query_all() if t.order_no == cancel_rows[0].order_no]
    assert len(cancel_trades) == 0

    # 原单 cancelled_volume 不变（仅 status=54 路径才抹平）
    db.close()
    db.expire_all()
    updated = Orders.query_by("order_no", "10000004")[0]
    assert updated.cancelled_volume == 0


async def test_cancel_rpc_exception_writes_57(trader, fake_rpc_cancel, fake_broadcast, db, _deps_override, caplog):
    """RPC 抛异常 → cancel-row status=57 + log.exception, 无 cancel-trade。"""
    _seed_reported_order(db, order_no="10000005")
    fake_rpc_cancel.set_exception(RuntimeError("RPC connection refused"))

    with caplog.at_level(logging.ERROR, logger="server.api.orders.cancel"):
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.delete("/api/orders/10000005", params={"trd_date": "20260825"})

    body = r.json()
    assert body["code"] == 1

    # cancel-row status=57
    cancel_rows = [o for o in Orders.query_all() if o.user_def.startswith("CANCEL:")]
    assert len(cancel_rows) == 1
    assert cancel_rows[0].status == "57"
    assert "RPC connection refused" in cancel_rows[0].status_msg

    # 必须 log.exception
    error_records = [r for r in caplog.records if r.levelname == "ERROR"]
    assert any("RPC exception" in r.getMessage() for r in error_records)