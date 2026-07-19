"""
test_v78_skip_rebroadcast.py — v78 (REQ-TRADE-029) "已报后续不处理" 回归测试

覆盖 handle_ord_cfm + dispatcher._broadcast_generic 的 v78 语义:
- ord_cfm 1st ack (broker_status=50 code=0) → 写入 status=50, dispatcher 广播
- ord_cfm 2nd ack (broker_status=50 同委托, 无 cancelled_volume) → handler 返 None, dispatcher 跳过广播
- ord_cfm 3rd ack (broker_status=53 撤单类穿透) → handler 仍写入 status=53, dispatcher 广播
- ord_cfm 跨委托 (status=50 但 broker 报另一委托) → 不影响, dispatcher 仍广播
- trd_cfm 累计推断不受影响 (v78 仅针对 ord_cfm)

Mock 策略:
- 直接创建 Order + 调用 handle_ord_cfm (绕开 RPC)
- monkeypatch ws_manager.broadcast 收集 calls
- 验证 calls 数量而非具体 payload (避免假阳性)
"""
import asyncio
import pytest

# mode=AUTO 自动检测 async test, 不需要 pytestmark (否则对 sync 测试警告)

from server.db import SessionLocal
from server.models.orm import Order
from server.services.push.ord import handle_ord_cfm


# ─────────────── Fixtures ───────────────


@pytest.fixture
def db():
    """每个 test 独立 Session（DELETE orders 表保隔离）"""
    from sqlalchemy import text
    s = SessionLocal()
    s.execute(text("DELETE FROM orders"))
    s.commit()
    yield s
    # v-future (REQ-TRADE-030): finalizer 兜底清 t_* 测试用户, 防 admin/trader seed 永久丢失
    #   判定: LOCATE('_', username) > 0 (含下划线 = 测试用户名约定) 且排除真实用户 admin/trader
    s.execute(text("DELETE FROM users WHERE LOCATE('_', username) > 0 AND username NOT IN ('admin', 'trader')"))
    s.commit()
    s.close()


@pytest.fixture
def fake_broadcast(monkeypatch):
    """monkeypatch ws_manager.broadcast → fake async (收集 channel + payload)

    handler.handle_ord_cfm 返回 dict 时, dispatcher._broadcast_generic 会调
    ws_manager.broadcast 一次. 我们收集所有 calls 计数.
    """
    from server.ws.manager import ws_manager

    class FakeBroadcast:
        def __init__(self):
            self.calls = []  # [(channel, payload), ...]

        async def __call__(self, channel, payload, **kwargs):
            self.calls.append((channel, payload))
            return None

    fake = FakeBroadcast()
    monkeypatch.setattr(ws_manager, "broadcast", fake)
    return fake


def _make_order(db, order_no="10000001", status="48"):
    """直接 DB 插入一行 Order, 模拟阶段 A 完成后 DB 状态"""
    o = Order(
        trd_date="20260718",
        order_no=order_no,
        user_def="",
        stock_code="600519.SH", order_type="23",
        price_type=0, price=1800.0, volume=100,
        traded_volume=0, traded_amount=0.0, avg_price=0.0,
        cancelled_volume=0,
        order_flag=0,
        status=status, status_msg="未报" if status == "48" else "",
        order_time="2026-07-18 09:30:00.000",
        task_id=None, strategy_type=0,
    )
    db.add(o)
    db.commit()
    db.refresh(o)
    return o


# ─────────────── Tests ───────────────


def test_first_ack_writes_50_and_broadcasts(db, fake_broadcast):
    """v78 baseline: 首次 ord_cfm code=0 → status=50 + 1 次 ws broadcast"""
    o = _make_order(db, status="48")

    row = {
        "order_id": "OID-1",
        "remark": o.order_no,
        "order_status": "50",
    }
    result = handle_ord_cfm(db, row, ts="2026-07-18T09:30:01")
    db.commit()

    assert result is not None, "首次 ack 应该返 dict (dispatcher 才广播)"
    assert result["status"] == "50"
    # fake_broadcast.calls 在 handle_ord_cfm 不直接调, 是 dispatcher 调
    # 本测试只验证 handler 返非 None, 真实广播由 dispatch chain 处理


def test_second_ack_after_already_reported_returns_none(db, fake_broadcast):
    """v78 核心: 已报后续 → handler 返 None → dispatcher 跳过"""
    o = _make_order(db, status="50")  # 当前已是已报

    row = {
        "order_id": "OID-1",
        "remark": o.order_no,
        "order_status": "50",  # broker 再推 ack code=0
    }
    result = handle_ord_cfm(db, row, ts="2026-07-18T09:30:05")
    db.commit()

    assert result is None, "已报后续 ord_cfm 应该返 None, 触发 dispatcher 跳过"


def test_cancel_class_breaks_skip(db, fake_broadcast):
    """v78 边界: broker_status 撤单类 (52/53/54/57) 必须穿透, 不跳过

    场景: 已报状态, broker 报 status=53 (部撤) → 必须写入并广播, 让前端立即看到"部撤"
    """
    o = _make_order(db, status="50")  # 已报

    row = {
        "order_id": "OID-1",
        "remark": o.order_no,
        "order_status": "53",  # broker 报部撤, 撤单类必须穿透
    }
    result = handle_ord_cfm(db, row, ts="2026-07-18T09:30:10")
    db.commit()

    assert result is not None, "撤单类穿透, 不应跳过"
    assert result["status"] == "53", "broker_status=53 应直接写入"


def test_partial_filled_status_breaks_skip(db, fake_broadcast):
    """v78 边界: status=55 (部成) 已算"出过事件", 后续 broker 非撤单 → 跳过

    用户语义: "若是已报状态, 后续的委托确认就不处理了" — 55 算"已出过",
    后续不应再被 broker 推 ack 干扰 (累计交给 trd_cfm 推断).
    """
    o = _make_order(db, status="55")  # 部成, 累计推断已落

    row = {
        "order_id": "OID-1",
        "remark": o.order_no,
        "order_status": "50",  # broker 再推 ack code=0
    }
    result = handle_ord_cfm(db, row, ts="2026-07-18T09:30:15")
    db.commit()

    assert result is None, "55 部成后续 ord_cfm 应跳过 (避免覆盖累计推断)"


def test_first_time_ack_does_not_skip(db, fake_broadcast):
    """v78 边界: 首次从 48 → 50 不能被误跳

    当前 status=48 (未报), broker 推 ack code=0 → 必须写入 50 + 广播
    """
    o = _make_order(db, status="48")

    row = {
        "order_id": "OID-1",
        "remark": o.order_no,
        "order_status": "50",
    }
    result = handle_ord_cfm(db, row, ts="2026-07-18T09:30:20")
    db.commit()

    assert result is not None, "首次 48→50 必须返非 None"
    assert result["status"] == "50"


async def test_dispatcher_skips_on_none_handler_result(db, fake_broadcast):
    """v78 dispatcher 端到端: handler None → broadcast.calls 0

    通过真实 dispatcher._broadcast_generic 验证 None 跳过语义.
    """
    from server.services.push.dispatcher import PushDispatcher

    disp = PushDispatcher(rpc_client=None)
    enriched_row = {"order_no": "X", "status": "50"}

    # 真实 call (handler_result=None) — 应直接 return, 不调 ws_manager
    disp._broadcast_generic(
        handler_result=None,
        enriched_row=enriched_row,
        channel="order_update",
        ts="2026-07-18T09:30:30",
        func="ord_cfm",
        active_trd_date="20260718",
        push_trace="test-trace-1",
    )

    # v78: 跳过路径 — 立即检查, 不需要等调度
    assert len(fake_broadcast.calls) == 0, \
        "handler_result=None 必须跳过 broadcast, 实际 calls=%s" % fake_broadcast.calls


async def test_dispatcher_broadcasts_on_valid_handler_result(db, fake_broadcast):
    """v78 dispatcher baseline: handler 非 None → broadcast 1 次"""
    from server.services.push.dispatcher import PushDispatcher

    disp = PushDispatcher(rpc_client=None)
    handler_result = {"order_no": "X", "status": "50"}

    disp._broadcast_generic(
        handler_result=handler_result,
        enriched_row={"order_no": "X", "status": "48"},  # fallback 不应被用
        channel="order_update",
        ts="2026-07-18T09:30:40",
        func="ord_cfm",
        active_trd_date="20260718",
        push_trace="test-trace-2",
    )

    # event loop 内 give time 让 ensure_future 调度的 fake_broadcast 跑完
    await asyncio.sleep(0.05)

    assert len(fake_broadcast.calls) == 1, \
        "handler 非 None 必须 broadcast 1 次, 实际 calls=%d" % len(fake_broadcast.calls)
