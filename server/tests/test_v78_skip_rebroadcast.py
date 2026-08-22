"""
test_v78_skip_rebroadcast.py — (REQ-TRADE-029) "已报后续不处理" 回归测试

覆盖 handle_ord_cfm + dispatcher._broadcast_generic 的语义:
- ord_cfm 1st ack (broker_status=50 code=0) → 写入 status=50, dispatcher 广播
- ord_cfm 2nd ack (broker_status=50 同委托, 无 cancelled_volume) → handler 返 None, dispatcher 跳过广播
- ord_cfm 3rd ack (broker_status=53 撤单类穿透) → handler 仍写入 status=53, dispatcher 广播
- ord_cfm 跨委托 (status=50 但 broker 报另一委托) → 不影响, dispatcher 仍广播
- trd_cfm 累计推断不受影响 (仅针对 ord_cfm)

Mock 策略:
- 直接创建 Order + 调用 handle_ord_cfm (绕开 RPC)
- monkeypatch ws_manager.broadcast 收集 calls
- 验证 calls 数量而非具体 payload (避免假阳性)
"""
import asyncio
import pytest

# mode=AUTO 自动检测 async test, 不需要 pytestmark (否则对 sync 测试警告)

from server.db import SessionLocal
from server.tables import Orders
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
    """直接 DB 插入一行 Order, 模拟阶段 A 完成后 DB 状态

    tables 层: Orders.upsert_one (复合 PK trd_date+order_no), 返回 Row
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


# ─────────────── Tests ───────────────


def test_first_ack_writes_50_and_broadcasts(db, fake_broadcast):
    """baseline: 首次 ord_cfm code=0 → status=50 + 1 次 ws broadcast"""
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
    """(REQ-TRADE-032): 50 在 PUSH_STATUSES → broker 重复推 50 仍推
    旧设计是"已报后续不推"，现在改成"只推 50/57",
    重复 50 是合法推送 (DB 写入幂等, 前端仍显示"已报").
    """
    o = _make_order(db, status="50")  # 当前已是已报

    row = {
        "order_id": "OID-1",
        "remark": o.order_no,
        "order_status": "50",  # broker 再推 ack code=0
    }
    result = handle_ord_cfm(db, row, ts="2026-07-18T09:30:05")
    db.commit()

    assert result is not None, "50 在 PUSH_STATUSES, broker 推 50 必须返回 dict"
    assert result["status"] == "50"


def test_cancel_class_not_pushed(db, fake_broadcast):
    """(REQ-TRADE-032): 撤单类 (52/53/54) 不在 PUSH_STATUSES → return None

    撤单由 api/orders/cancel.py 主动 INSERT cancel-trade (trade_type=1)
    走 trd_cfm 路径推送, 前端通过成交通知感知撤单完成.
    """
    o = _make_order(db, status="50")  # 已报

    row = {
        "order_id": "OID-1",
        "remark": o.order_no,
        "order_status": "53",  # broker 报部撤, 不在 PUSH_STATUSES → 跳过
    }
    result = handle_ord_cfm(db, row, ts="2026-07-18T09:30:10")
    db.commit()

    assert result is None, "53 不在 PUSH_STATUSES, broker 推部撤应跳过"


def test_partial_filled_status_pushed_on_50(db, fake_broadcast):
    """(REQ-TRADE-032): 当前=55 部成, broker 再推 50 → 仍推 (50 在 PUSH_STATUSES)

    旧设计 55 后跳 50 是为"防止覆盖累计", 现在改成"只推 50/57",
    broker 推 50 总是推 (前端显示已报), 累计靠 trd_cfm 推断, 不怕覆盖.
    """
    o = _make_order(db, status="55")  # 部成, 累计推断已落

    row = {
        "order_id": "OID-1",
        "remark": o.order_no,
        "order_status": "50",  # broker 再推 ack code=0
    }
    result = handle_ord_cfm(db, row, ts="2026-07-18T09:30:15")
    db.commit()

    assert result is not None, "50 在 PUSH_STATUSES, broker 推 50 必须返回 dict"
    assert result["status"] == "50", "broker_status=50 → order.status=50 (非 55)"


def test_first_time_ack_does_not_skip(db, fake_broadcast):
    """边界: 首次从 48 → 50 不能被误跳

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
    """dispatcher 端到端: handler None → broadcast.calls 0

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

    # 跳过路径 — 立即检查, 不需要等调度
    assert len(fake_broadcast.calls) == 0, \
        "handler_result=None 必须跳过 broadcast, 实际 calls=%s" % fake_broadcast.calls


async def test_dispatcher_broadcasts_on_valid_handler_result(db, fake_broadcast):
    """dispatcher baseline: handler 非 None → broadcast 1 次"""
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
