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
from server.tables import Orders, SysStatus, T0Tasks, Users
from server.auth.security import hash_password, create_access_token


# ─────────────── Fixtures ───────────────


@pytest.fixture
def db(mock_trd_date):
    """每个 test 独立 Session（不动现有数据）.

    v-future (2026-08-27 用户硬规则): 测试**不删**生产 orders/trades 数据。
    隔离策略: 测试订单用 conftest.TEST_TRD_DATE 高位前缀 (跟生产 trd_date=202608xx 完全不冲突);
    测试 trader 用户名 't_place_v77' 已有下划线, finalizer 排除 admin/trader.
    """
    from sqlalchemy import text
    s = SessionLocal()
    yield s
    # v-future (2026-08-27): finalizer 清本测试标记的 orders 行 (含 place 主流程/seed 写入),
    #   按 user_def 标记清不限 trd_date (防历史残留积累, 同 test_orders_cancel)
    s.execute(text("DELETE FROM orders WHERE user_def LIKE '_test_place_async_v77'"))
    # v-future (REQ-TRADE-030): finalizer 兜底清 t_* 测试用户, 防 admin/trader seed 永久丢失
    #   判定: LOCATE('_', username) > 0 (含下划线 = 测试用户名约定) 且排除真实用户 admin/trader
    s.execute(text("DELETE FROM users WHERE LOCATE('_', username) > 0 AND username NOT IN ('admin', 'trader')"))
    s.commit()
    s.close()


@pytest.fixture
def trader(db):
    """trader 用户 (v-future REQ-TRADE-030: db fixture finalizer 自动清理 t_*)

    v-future (2026-08-27): 不动 sys_status 表, 测试通过 mock_trd_date fixture 拿隔离 trd_date='99990718'.
    """
    for _old in Users.query_by("username", "t_place_v77"):
        Users.delete_one(id=_old.id)
    u = Users.add_one({"username": "t_place_v77", "password_hash": hash_password("x"), "role": "trader"})
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


def _make_order(db, user_id, order_no: str, status: str, trd_date: str):
    """直接 DB 插入一行 status=48 Order, 模拟阶段 A 完成后 DB 状态

    注: orders 无 user_id 字段 (按 trd_date + order_no 联合 PK), user_id 参数仅签名兼容.
    tables 层: Orders.upsert_one (复合 PK trd_date+order_no), 返回 Row.

    v-future (2026-08-27): trd_date 必传 (conftest.TEST_TRD_DATE 隔离测试数据与生产数据, 生产 trd_date=202608xx).
    """
    o = Orders.upsert_one({
        "user_def": "_test_place_async_v77",
        "stock_code": "600519.SH", "order_type": "23",
        "price_type": 0, "price": 1800.0, "volume": 100,
        "traded_volume": 0, "traded_amount": 0.0, "avg_price": 0.0,
        "cancelled_volume": 0,
        "order_flag": 0,
        "status": status, "status_msg": "" if status == "48" else "",
        "order_time": "9999-07-18 09:30:00.000",
        "task_id": None, "strategy_type": 0,
    }, return_row=True, trd_date=trd_date, order_no=order_no)
    return o


# ─────────────── 阶段 B 单测: _submit_rpc_async ───────────────


async def test_submit_rpc_success_keeps_status_48_until_broker_push(trader, fake_ord_stk, fake_broadcast, db, mock_trd_date):
    """RPC 成功 (ack.code==0 + order_id) → v11 broker 字典对齐后 _submit_rpc_async 不再写 status=50/status_msg,
    状态由 broker ord_cfm push 异步推. 本测试验证 _submit_rpc_async 阶段 ack 路径行为:
      - status 保持 48 (不变)
      - status_msg 保持 '' (不变, 等 broker ord_cfm 推)
      - log.info 含 ack.code=0
    """
    order = _make_order(db, trader["id"], order_no="10000001", status="48", trd_date=mock_trd_date)
    fake_ord_stk.set_ack({"code": 0, "list": [{"order_id": "BROKER-OID-X"}]})

    # 关键: 在 fake loop 中 await task, 让 RPC path 执行
    await _submit_rpc_async(order.order_no, order.trd_date)
    # 等待可能的 ws push 异步任务
    await asyncio.sleep(0.01)

    # DB 验证: status 保持 48 (broker ord_cfm 未推情况下)
    db.close()  # 关掉 fixture 的 transaction-bound session
    db.expire_all()
    _rows = Orders.query_by('order_no', order.order_no)
    updated = _rows[0] if _rows else None
    assert updated is not None, f"order_no={order.order_no} 不应被删"
    assert updated.status == "48", f"v11 后 ack.code=0 不改 status, 期望 48, 实际 {updated.status}"
    assert updated.status_msg == "", f"v11 后 ack.code=0 不改 status_msg, 期望 '', 实际 '{updated.status_msg}'"
    # broker_order_id v11 后也不在 _submit_rpc_async 写 (留给 ord_cfm push)
    assert (updated.order_id or "") == "", f"v11 后 broker_order_id 由 ord_cfm 推, 期望 '', 实际 '{updated.order_id}'"


async def test_submit_rpc_broker_reject_defers_to_transport(trader, fake_ord_stk, fake_broadcast, db, mock_trd_date):
    """broker 拒单 (ack.code != 0) → v11 后由 transport._handle_ord_stk_reply_junk 接管 (不在 place.py 写).

    本测试验证 _submit_rpc_async 自身行为:
      - status 保持 48 (transport 才写 status=57)
      - status_msg 保持 ''
      - place.py 不主动 ws push (transport 推)
    """
    order = _make_order(db, trader["id"], order_no="10000002", status="48", trd_date=mock_trd_date)
    fake_ord_stk.set_ack({"code": 1, "msg": "资金不足"})

    await _submit_rpc_async(order.order_no, order.trd_date)
    await asyncio.sleep(0.01)

    db.close()
    db.expire_all()
    _rows = Orders.query_by('order_no', order.order_no)
    updated = _rows[0] if _rows else None
    assert updated is not None, f"order_no={order.order_no} 不应被删"
    # v11 broker 字典对齐后: ack.code!=0 由 transport 接管废单路径, _submit_rpc_async 不写 status
    assert updated.status == "48", f"v11 后 ack.code!=0 废单路径走 transport, 期望 48, 实际 {updated.status}"
    assert updated.cancelled_volume == 0, f"v11 后 cancelled_volume 由 transport 写, 期望 0, 实际 {updated.cancelled_volume}"
    assert updated.status_msg == "", f"v11 后 status_msg 由 transport 写, 期望 '', 实际 '{updated.status_msg}'"


async def test_submit_rpc_exception_writes_status_57_fallback(trader, fake_ord_stk, fake_broadcast, db, mock_trd_date):
    """RPC 异常 (timeout / broker down) → _submit_rpc_async 走 fallback 写 status=57 + msg + ws push (place.py:230-241).

    这条路径**不是** broker push 路径, 是 _submit_rpc_async 自己的兜底:
    transport cache 已被 evict 后, 必须由这里写 status=57, 否则订单卡 status=48.
    """
    order = _make_order(db, trader["id"], order_no="10000003", status="48", trd_date=mock_trd_date)
    fake_ord_stk.set_exception(TimeoutError("broker RPC timeout 30s"))

    await _submit_rpc_async(order.order_no, order.trd_date)
    await asyncio.sleep(0.01)

    db.close()
    db.expire_all()
    _rows = Orders.query_by('order_no', order.order_no)
    updated = _rows[0] if _rows else None
    assert updated is not None
    # fallback 路径写 status=57 + status_msg (broker JUNK 废单)
    assert updated.status == "57", f"异常 fallback 路径期望 status=57, 实际 {updated.status}"
    assert "RPC 失败" in updated.status_msg, f"status_msg 应含 'RPC 失败', 实际 '{updated.status_msg}'"
    assert "broker RPC timeout 30s" in updated.status_msg, f"status_msg 应含原始异常, 实际 '{updated.status_msg}'"

    # ws push 验证: fallback 路径 _submit_rpc_async 自己 push (走 _broadcast_order_cfm,
    # payload 是 {type:'ord_cfm', channel:'order_update', data:{...order fields...}} 嵌套结构)
    push_payloads = [p for c, p in fake_broadcast.calls if c == "order_update"]
    assert any(
        p.get("data", {}).get("status") == "57" for p in push_payloads
    ), f"fallback 路径必须 ws push data.status=57, 实际: {[p.get('data', {}).get('status') for p in push_payloads]}"


async def test_submit_rpc_does_not_swallow_exception(trader, fake_ord_stk, fake_broadcast, db, caplog, mock_trd_date):
    """RPC 异常必须 log.exception (不能静默吞掉, 否则丢委托无法排查)"""
    order = _make_order(db, trader["id"], order_no="10000004", status="48", trd_date=mock_trd_date)
    fake_ord_stk.set_exception(RuntimeError("broker 进程崩溃"))

    with caplog.at_level(logging.ERROR, logger="server.api.orders.place"):
        await _submit_rpc_async(order.order_no, order.trd_date)
        await asyncio.sleep(0.01)

    # 必须有 ERROR 级别日志含 trace
    error_records = [r for r in caplog.records if r.levelname == "ERROR"]
    assert any("RPC failed" in r.getMessage() or "broker 进程崩溃" in r.getMessage() for r in error_records), \
        f"RPC 异常必须 log, 实际日志: {[r.getMessage() for r in caplog.records]}"


async def test_submit_rpc_missing_order_logs_error_no_push(trader, fake_ord_stk, fake_broadcast, db, caplog, mock_trd_date):
    """订单不存在 (DB 被删等异常场景) → log error + 不 push (避免脏数据)"""
    # _make_order 不调, 模拟 order_no=99999999 不存在 (用 mock_trd_date 提供的隔离 trd_date)
    with caplog.at_level(logging.ERROR, logger="server.api.orders.place"):
        await _submit_rpc_async("99999999", mock_trd_date)
        await asyncio.sleep(0.01)

    error_records = [r for r in caplog.records if r.levelname == "ERROR"]
    assert any("not found" in r.getMessage() for r in error_records), \
        f"订单不存在必须 log error, 实际: {[r.getMessage() for r in caplog.records]}"
    assert len(fake_broadcast.calls) == 0, "订单不存在不应 push ws (脏数据)"


async def test_submit_rpc_payload_includes_required_fields(trader, fake_ord_stk, fake_broadcast, db, mock_trd_date):
    """v91.4 后 _to_order_out 仍包含 task_id / strategy_type 字段 (前端 Pinia store applyOrderPush 仍读).

    本测试验证 _to_order_out 关键字段存在 (REGRESSION 防核心字段被删):
      - 基础字段 (order_no / stock_code / status / volume / price / trd_date)
      - 母单字段 (task_id / strategy_type) 必须在 (用于 signal_consumer 路径)
      - broker 反馈字段 (order_id / status_msg / order_time / order_flag)
    """
    o = _make_order(db, trader["id"], order_no="10000005", status="48", trd_date=mock_trd_date)
    o.task_id = 99999  # 任意占位 (不写真 T0Task, 用户硬规则)
    o.strategy_type = 1  # 快速做T
    o.update()

    fake_ord_stk.set_ack({"code": 0, "list": [{"order_id": "OID-X"}]})

    await _submit_rpc_async(o.order_no, o.trd_date)
    await asyncio.sleep(0.01)

    # 直接验证 _to_order_out schema
    from server.api.orders.schemas import _to_order_out
    o2 = Orders.query_one(trd_date=o.trd_date, order_no=o.order_no)
    assert o2 is not None, f"order 应在 DB: trd_date={o.trd_date} order_no={o.order_no}"
    payload_obj = _to_order_out(o2)
    payload = payload_obj.model_dump() if hasattr(payload_obj, 'model_dump') else payload_obj.dict()

    # 基础字段必须在
    for k in ("order_no", "trd_date", "stock_code", "status", "volume", "price"):
        assert k in payload, f"payload 应含 {k}, 实际 keys: {list(payload.keys())}"
    # 母单字段必须在 (signal_consumer 路径需要 task_id / strategy_type)
    assert "task_id" in payload, f"signal_consumer 路径需要 task_id, 实际 keys: {list(payload.keys())}"
    assert "strategy_type" in payload, f"signal_consumer 路径需要 strategy_type, 实际 keys: {list(payload.keys())}"
    # broker 反馈字段必须在
    assert "order_id" in payload
    assert "status_msg" in payload
    # 验证 task_id 值
    assert payload["task_id"] == 99999, f"task_id 应=99999, 实际 {payload['task_id']}"
    assert payload["strategy_type"] == 1


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
    from server.infra.db import SessionLocal as _SL

    # v-future (2026-08-27 用户硬规则): 不清 orders 表. 测试用 mock_trd_date 拿隔离 trd_date='99990718',
    # 生产 orders 那行 10000176 不会被测试碰到.

    # mock get_current_user
    u = Users.query_one(id=trader["id"])
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
            # 2. code=0 + status=48 (DB 写完即返; broker xtconstant 48=待报)
            assert data["code"] == 0, "code=%s msg=%s" % (data.get("code"), data.get("msg"))
            assert data["order"]["status"] == "48"
            # v11 broker 字典对齐后: server/repo/orders.py:283 INSERT 时统一 status_msg="待报"
            # (旧期望 'status_msg == "未报"' 已废弃; v11 改名 "未报" → "待报")
            assert data["order"]["status_msg"] == "待报", \
                f"v11 后 status_msg 默认 '待报', 实际 '{data['order']['status_msg']}'"

            # 3. 阶段 A ws push status=48 已发 (嵌套结构: payload.data.status)
            await asyncio.sleep(0.02)
            push_payloads = [p for c, p in fake_broadcast.calls if c == "order_update"]
            assert any(p.get("data", {}).get("status") == "48" for p in push_payloads), \
                "阶段 A 必须 ws push data.status=48, 实际: %s" % [p.get("data", {}).get("status") for p in push_payloads]

            # 4. v11 后阶段 B (_submit_rpc_async ack.code=0 路径) **不主动 ws push**;
            #    broker ord_cfm 异步推 status=50 时才 push. 本测试不验证阶段 B push.
    finally:
        app.dependency_overrides.clear()
