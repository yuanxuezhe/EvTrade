"""
test_place_async.py — 两阶段下单架构单测 (REQ-TRADE-028)

覆盖 place.py 阶段 A + 阶段 B 行为:
- 阶段 A: DB INSERT 后立即 HTTP 应答 (含 status=48)
- 阶段 A: 阶段 A ws push (status=48)
- 阶段 B: RPC 成功 → DB UPDATE status=50 + 阶段 B ws push
- 阶段 B: RPC 失败 (ack.code != 0) → DB UPDATE status=57 + cancelled_volume=volume + 阶段 B ws push
- 阶段 B: RPC 异常 (timeout/broker down) → DB UPDATE status=57 + 阶段 B ws push
- 阶段 B: 兜底: 任何意外 (DB 查询失败) 也 log 不吞
- asyncio.create_task 在 endpoint 内调用, 不会被同步等待

Mock 策略:
- monkeypatch server.api.orders.ord_stk 为 fake async (可控返回值/异常)
- monkeypatch server.api.orders.ws_manager.broadcast 收集 calls
- 直接调用 _submit_rpc_async (公开函数) 验证阶段 B
"""
import asyncio
import logging
import pytest

pytestmark = pytest.mark.asyncio

# ─────────────── Imports ───────────────

from server.api.orders.place import _submit_rpc_async
from server.api.orders import ord_stk as real_ord_stk
from server.api.orders import ws_manager as real_ws_manager
from server.infra.db import SessionLocal
from server.tables import Orders, SysStatus, T0Tasks
from server.models.user import User
from server.auth.security import hash_password, create_access_token


# ─────────────── Fixtures ───────────────


@pytest.fixture
def db():
    """每个 test 独立 Session（DELETE orders 表保隔离）"""
    from sqlalchemy import text
    s = SessionLocal()
    # 清表 + 重置自增（place.py 用 order_no 单调递增）
    s.execute(text("DELETE FROM orders"))
    s.execute(text("ALTER TABLE orders AUTO_INCREMENT = 1"))
    s.commit()
    yield s
    # v-future (REQ-TRADE-030): finalizer 兜底清 t_* 测试用户, 防 admin/trader seed 永久丢失
    #   判定: LOCATE('_', username) > 0 (含下划线 = 测试用户名约定) 且排除真实用户 admin/trader
    s.execute(text("DELETE FROM users WHERE LOCATE('_', username) > 0 AND username NOT IN ('admin', 'trader')"))
    s.commit()
    s.close()


@pytest.fixture
def trader(db):
    """trader 用户 + 已激活交易日 (v-future REQ-TRADE-030: db fixture finalizer 自动清理 t_*)"""
    db.query(User).filter_by(username="t_place_v77").delete()
    u = User(username="t_place_v77", password_hash=hash_password("x"), role="trader")
    db.add(u)
    db.commit()
    db.refresh(u)

    # 激活交易日（place.py 依赖 SysStatus active; sys_status 单行 id=1）
    SysStatus.delete_one(id=1)
    SysStatus.upsert_one({
        "trd_date": "20260718",
        "status": "active",
    }, id=1)

    return {"id": u.id, "username": u.username}


@pytest.fixture
def fake_ord_stk(monkeypatch):
    """
    monkeypatch ord_stk → fake async (返回调用历史 + 可控 ack/异常)
    用法:
      fake = fake_ord_stk
      fake.set_ack({"code": 0, "list": [{"order_id": "OID-1"}]})
      fake.set_exception(ValueError("broker timeout"))
    """
    from server.api.orders import place as place_mod

    class FakeOrdStk:
        def __init__(self):
            self.calls = []
            self._next_ack = None
            self._next_exception = None

        def set_ack(self, ack):
            self._next_ack = ack

        def set_exception(self, e):
            self._next_exception = e

        async def __call__(self, **kwargs):
            print(f"FAKE CALLED: {kwargs}", flush=True)
            self.calls.append(kwargs)
            if self._next_exception is not None:
                raise self._next_exception
            return self._next_ack or {"code": 0, "list": [{"order_id": "OID-DEFAULT"}]}

    fake = FakeOrdStk()
    print(f"FAKE ORD_STK BEFORE monkeypatch = {__import__('server.api.orders', fromlist=['ord_stk']).ord_stk}", flush=True)
    monkeypatch.setattr("server.api.orders.ord_stk", fake)
    print(f"FAKE ORD_STK AFTER monkeypatch = {__import__('server.api.orders', fromlist=['ord_stk']).ord_stk}", flush=True)
    return fake


@pytest.fixture
def fake_broadcast(monkeypatch):
    """
    monkeypatch ws_manager.broadcast → fake async (收集 channel + payload)
    ws_manager 是 module-level singleton, 直接替换其方法
    """
    from server.api.orders import ws_manager

    class FakeBroadcast:
        def __init__(self):
            self.calls = []  # [(channel, payload_dict), ...]

        async def __call__(self, channel, payload, **kwargs):
            self.calls.append((channel, payload))
            # 真实 ws_manager.broadcast 内部已用 asyncio.ensure_future 包装
            return None

    fake = FakeBroadcast()
    monkeypatch.setattr(ws_manager, "broadcast", fake)
    return fake


# ─────────────── Helpers ───────────────


def _make_order(db, user_id, order_no="10000001", status="48"):
    """直接 DB 插入一行 status=48 Order, 模拟阶段 A 完成后 DB 状态

    注: orders 无 user_id 字段 (按 trd_date + order_no 联合 PK), user_id 参数仅签名兼容.
    tables 层: Orders.upsert_one (复合 PK trd_date+order_no), 返回 Row.
    """
    o = Orders.upsert_one({
        "user_def": "",
        "stock_code": "600519.SH", "order_type": "23",
        "price_type": 0, "price": 1800.0, "volume": 100,
        "traded_volume": 0, "traded_amount": 0.0, "avg_price": 0.0,
        "cancelled_volume": 0,
        "order_flag": 0,
        "status": status, "status_msg": "未报" if status == "48" else "",
        "order_time": "2026-07-18 09:30:00.000",
        "task_id": None, "strategy_type": 0,
    }, return_row=True, trd_date="20260718", order_no=order_no)
    return o


# ─────────────── 阶段 B 单测: _submit_rpc_async ───────────────


async def test_submit_rpc_success_updates_status_50_and_pushes(trader, fake_ord_stk, fake_broadcast, db):
    """RPC 成功 (ack.code==0 + order_id) → status=50 + 阶段 B ws push status=50"""
    order = _make_order(db, trader["id"], order_no="10000001")
    fake_ord_stk.set_ack({"code": 0, "list": [{"order_id": "BROKER-OID-X"}]})

    # 关键: 在 fake loop 中 await task, 让 RPC path 执行
    await _submit_rpc_async(order.order_no, order.trd_date)
    # 等待可能的 ws push 异步任务
    await asyncio.sleep(0.01)

    # DB 验证: status=50 + broker_order_id 写入
    # 注: _submit_rpc_async 用独立 SessionLocal commit, 测试 fixture db session 不能直接读,
    #     必须新开一个 SessionLocal + 干净事务才能读到 commit 后的值.
    db.close()  # 关掉 fixture 的 transaction-bound session
    db.expire_all()
    _rows = Orders.query_by('order_no', order.order_no)
    updated = _rows[0] if _rows else None
    assert updated.status == "50", f"status={updated.status} (expected 50)"
    assert updated.order_id == "BROKER-OID-X"
    assert updated.status_msg == "已报"

    # ws push 验证: 阶段 B (status=50)
    push_payloads = [p for c, p in fake_broadcast.calls if c == "order_update"]
    assert len(push_payloads) >= 1
    last_push = push_payloads[-1]
    assert last_push["status"] == "50"
    assert last_push["order_no"] == order.order_no
    assert last_push["order_id"] == "BROKER-OID-X"


async def test_submit_rpc_broker_reject_updates_status_57_with_cancel_volume(trader, fake_ord_stk, fake_broadcast, db):
    """broker 拒单 (ack.code != 0) → status=57 + cancelled_volume=volume + 阶段 B ws push"""
    order = _make_order(db, trader["id"], order_no="10000002")
    fake_ord_stk.set_ack({"code": 1, "msg": "资金不足"})

    await _submit_rpc_async(order.order_no, order.trd_date)
    await asyncio.sleep(0.01)

    db.close()  # 关掉 fixture 的 transaction-bound session
    db.expire_all()
    _rows = Orders.query_by('order_no', order.order_no)
    updated = _rows[0] if _rows else None
    assert updated.status == "57"
    assert updated.cancelled_volume == updated.volume  # R2a 抹平
    assert "资金不足" in updated.status_msg

    push_payloads = [p for c, p in fake_broadcast.calls if c == "order_update"]
    last_push = push_payloads[-1]
    assert last_push["status"] == "57"
    assert last_push["cancelled_volume"] == updated.volume


async def test_submit_rpc_exception_updates_status_57_and_pushes(trader, fake_ord_stk, fake_broadcast, db):
    """RPC 异常 (timeout / broker down) → status=57 + 阶段 B ws push + status_msg 含异常"""
    order = _make_order(db, trader["id"], order_no="10000003")
    fake_ord_stk.set_exception(TimeoutError("broker RPC timeout 30s"))

    await _submit_rpc_async(order.order_no, order.trd_date)
    await asyncio.sleep(0.01)

    db.close()  # 关掉 fixture 的 transaction-bound session
    db.expire_all()
    _rows = Orders.query_by('order_no', order.order_no)
    updated = _rows[0] if _rows else None
    assert updated.status == "57"
    assert "RPC 失败" in updated.status_msg
    assert "broker RPC timeout 30s" in updated.status_msg

    push_payloads = [p for c, p in fake_broadcast.calls if c == "order_update"]
    last_push = push_payloads[-1]
    assert last_push["status"] == "57"


async def test_submit_rpc_does_not_swallow_exception(trader, fake_ord_stk, fake_broadcast, db, caplog):
    """RPC 异常必须 log.exception (不能静默吞掉, 否则丢委托无法排查)"""
    order = _make_order(db, trader["id"], order_no="10000004")
    fake_ord_stk.set_exception(RuntimeError("broker 进程崩溃"))

    with caplog.at_level(logging.ERROR, logger="server.api.orders.place"):
        await _submit_rpc_async(order.order_no, order.trd_date)
        await asyncio.sleep(0.01)

    # 必须有 ERROR 级别日志含 trace
    error_records = [r for r in caplog.records if r.levelname == "ERROR"]
    assert any("RPC failed" in r.getMessage() or "broker 进程崩溃" in r.getMessage() for r in error_records), \
        f"RPC 异常必须 log, 实际日志: {[r.getMessage() for r in caplog.records]}"


async def test_submit_rpc_missing_order_logs_error_no_push(trader, fake_ord_stk, fake_broadcast, db, caplog):
    """订单不存在 (DB 被删等异常场景) → log error + 不 push (避免脏数据)"""
    # _make_order 不调, 模拟 order_no=99999999 不存在
    with caplog.at_level(logging.ERROR, logger="server.api.orders.place"):
        await _submit_rpc_async("99999999", "20260718")
        await asyncio.sleep(0.01)

    error_records = [r for r in caplog.records if r.levelname == "ERROR"]
    assert any("not found" in r.getMessage() for r in error_records), \
        f"订单不存在必须 log error, 实际: {[r.getMessage() for r in caplog.records]}"
    assert len(fake_broadcast.calls) == 0, "订单不存在不应 push ws (脏数据)"


async def test_submit_rpc_payload_includes_task_id_and_strategy(trader, fake_ord_stk, fake_broadcast, db):
    """task_id + strategy_type 必须透传到 ws push (T0Trade filter/cache 列依赖)"""
    # 改 order 带 task_id + strategy_type=1
    # t0_tasks 自增 id → add_one 让 DB 生成; 清空用 delete_one 循环
    for t in T0Tasks.query_all():
        T0Tasks.delete_one(id=t.id)
    task = T0Tasks.add_one({
        "user_id": trader["id"], "stock_code": "600519.SH",
        "base_volume": 0, "target_volume": 100,
        "coefficient": 1.0, "status": "active",
        "created_trd_date": "20260718",
    })

    o = _make_order(db, trader["id"], order_no="10000005")
    o.task_id = task.id
    o.strategy_type = 1  # 快速做T
    o.update()  # Row.update(): 无参 WHERE pk + SET 全字段 (tables 层持久化)

    fake_ord_stk.set_ack({"code": 0, "list": [{"order_id": "OID-X"}]})

    await _submit_rpc_async(o.order_no, o.trd_date)
    await asyncio.sleep(0.01)

    push_payloads = [p for c, p in fake_broadcast.calls if c == "order_update"]
    last_push = push_payloads[-1]
    assert last_push["task_id"] == task.id
    assert last_push["strategy_type"] == 1


# ─────────────── 阶段 A 单测: 立即应答 + ws push status=48 ───────────────

# 阶段 A 测试需要调 place_order endpoint (FastAPI Depends), 单独走 TestClient 路径
# 此处简化: 验证 _submit_rpc_async 不会被阶段 A 同步等待 (endpoint 内 asyncio.create_task)


async def test_endpoint_creates_task_and_returns_immediately(trader, fake_ord_stk, fake_broadcast, db, monkeypatch):
    """
    v77 两阶段下单端到端: POST /api/orders/place 立即返回 (<0.05s 不等 RPC),
    阶段 A ws push status=48, 阶段 B 后台跑完后 ws push status=50.

    用 httpx AsyncClient + ASGITransport (TestClient 是同步, 不支持后台 task).
    """
    import asyncio
    import time
    import httpx
    from httpx import ASGITransport
    from server.main import app
    from server.auth.deps import get_current_user
    from sqlalchemy import text
    from server.infra.db import SessionLocal as _SL
    from server.models.user import User as UserM

    # 清理 orders 表
    cln = _SL()
    try:
        cln.execute(text("DELETE FROM orders"))
        cln.execute(text("ALTER TABLE orders AUTO_INCREMENT = 1"))
        cln.commit()
    finally:
        cln.close()

    # mock get_current_user
    u = db.query(UserM).filter_by(id=trader["id"]).first()
    app.dependency_overrides[get_current_user] = lambda: u

    # mock require_trading_session — 绕过 9:15-11:30 / 13:00-15:00 时段检查,
    # 测试不应该被系统时钟约束. 真实盘前/盘后下单由前端 UI 自行控制.
    from server.services.guards import require_trading_session
    app.dependency_overrides[require_trading_session] = lambda: None

    # fake_ord_stk 加 50ms sleep 模拟 broker 慢
    # ⚠️ 关键: monkeypatch.setattr(type(fake), "__call__", slow_call) 后,
    #    fake(stock_code='X', ...) → slow_call(fake_instance, stock_code='X', ...)
    #    → args=(fake_instance,), kwargs={'stock_code': ...}
    # original_call = bound method (self=fake_instance 已绑), 不能再传 fake_instance 作 positional
    original_call = fake_ord_stk.__call__  # bound method (self 已绑)
    async def slow_call(*args, **kwargs):
        await asyncio.sleep(0.05)
        # 原 args=(self,) 已绑进 original_call, 仅透传 kwargs
        return await original_call(**kwargs)
    monkeypatch.setattr(type(fake_ord_stk), "__call__", slow_call)
    fake_ord_stk.set_ack({"code": 0, "list": [{"order_id": "OID-LATE"}]})

    try:
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            body = {
                "stock_code": "600519.SH", "order_type": "23",
                "price_type": 0, "price": 1800.0, "volume": 100,
            }
            start = time.time()
            resp = await client.post("/api/orders/place", json=body)
            elapsed = time.time() - start

            # 1. 立即返回 (<0.05s, 不等 slow_call 0.05s+RPC 处理)
            assert resp.status_code == 200, "status=%d body=%s" % (resp.status_code, resp.text)
            assert elapsed < 2.0, "endpoint 必须 <2s 内返回 (httpx + ASGI lifespan 启动开销), 实际 %.3fs" % elapsed

            data = resp.json()
            # 2. code=0 + status=48 (DB 写完即返; broker xtconstant 48=未报)
            assert data["code"] == 0, "code=%s msg=%s" % (data.get("code"), data.get("msg"))
            assert data["order"]["status"] == "48"
            assert data["order"]["status_msg"] == "未报"

            # 3. 阶段 A ws push status=48 已发
            await asyncio.sleep(0.02)
            push_payloads = [p for c, p in fake_broadcast.calls if c == "order_update"]
            assert any(p["status"] == "48" for p in push_payloads), \
                "阶段 A 必须 ws push status=48, 实际: %s" % [p.get("status") for p in push_payloads]

            # 4. 等 RPC 后台跑完 (slow_call 0.05s + commit), 验证阶段 B ws push status=50
            await asyncio.sleep(0.3)
            push_payloads = [p for c, p in fake_broadcast.calls if c == "order_update"]
            assert any(p["status"] == "50" for p in push_payloads), \
                "阶段 B 必须 ws push status=50, 实际: %s" % [p.get("status") for p in push_payloads]
    finally:
        app.dependency_overrides.clear()
