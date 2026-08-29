"""
server/tests/strategy/test_task_progress_consumer.py — task_progress_consumer 单测

覆盖:
- _handle_message 解析 payload → ws_manager.broadcast 1 次
- payload 缺 task_id → ack + skip + 0 broadcast
- payload 非 dict → ack + skip
- JSON 解析失败 → ack + skip
- ws broadcast payload 格式 (type='task_progress', channel='task_progress_update', data={原始 payload})
- ws broadcast 失败 → 仍然 ack (best-effort)

策略:
- 不连 RabbitMQ: 直接 new TaskProgressConsumer() → 手动构造 aio_pika.IncomingMessage-like
- monkeypatch ws_manager.broadcast 收集 calls
- 不动 orders/trades/strategy_task (conftest autouse 仅清 orders.trd_date=99990718,
  本测试不创建 order, 无副作用)
"""

import asyncio
import json
from typing import Any, Dict, List, Optional

import pytest

pytestmark = pytest.mark.asyncio


# ─────────────── Fakes ───────────────


class FakeMessage:
    """模拟 aio_pika.abc.AbstractIncomingMessage — 仅实现 consumer 需要的接口"""

    def __init__(self, body: Any):
        # body 接受 dict (序列化为 JSON) 或 str (原始 JSON) 或 bytes
        if isinstance(body, dict):
            self._body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            self._body = body.encode("utf-8")
        elif isinstance(body, bytes):
            self._body = body
        else:
            raise TypeError(f"unsupported body type: {type(body)}")
        self.acked = False
        self.reject_args: Optional[List[Any]] = None

    def json(self) -> Dict[str, Any]:
        return json.loads(self._body.decode("utf-8"))

    async def ack(self) -> None:
        self.acked = True

    async def reject(self, requeue: bool = False) -> None:
        self.acked = False
        self.reject_args = [requeue]


class FakeBroadcast:
    """模拟 ws_manager.broadcast — 收集 (channel, payload) calls"""

    def __init__(self):
        self.calls: List[tuple] = []
        self.fail_first_n = 0  # 测试 ws 异常路径

    async def __call__(self, channel: str, payload: Dict[str, Any], **kwargs):
        if self.fail_first_n > 0:
            self.fail_first_n -= 1
            raise RuntimeError("fake ws broadcast error")
        self.calls.append((channel, payload))


# ─────────────── Fixtures ───────────────


@pytest.fixture
def fake_broadcast(monkeypatch):
    """monkeypatch ws_manager.broadcast → FakeBroadcast"""
    from server.services.strategy import task_progress_consumer as tpc_mod

    fake = FakeBroadcast()
    monkeypatch.setattr(tpc_mod.ws_manager, "broadcast", fake)
    return fake


@pytest.fixture
def consumer():
    """直接 new 一个 TaskProgressConsumer — 不起 RabbitMQ 连接 (仅测 _handle_message)"""
    from server.services.strategy.task_progress_consumer import TaskProgressConsumer

    return TaskProgressConsumer()


# ─────────────── Tests ───────────────


async def test_handle_message_broadcasts_task_progress(consumer, fake_broadcast):
    """正常 payload → ws_manager.broadcast 1 次, payload 含 type/channel/data"""
    payload = {
        "type": "task_progress_update",
        "task_id": 14,
        "status": "running",
        "progress": {
            "phase": "running",
            "msg": "回测中 bar=42/240",
            "bar_idx": 42,
            "total_bars": 240,
        },
        "ts": "2026-08-29T12:34:56",
    }
    msg = FakeMessage(payload)

    await consumer._handle_message(msg)

    assert msg.acked, "应 ack"
    assert len(fake_broadcast.calls) == 1, f"应 broadcast 1 次, 实际 {len(fake_broadcast.calls)}"

    channel, ws_payload = fake_broadcast.calls[0]
    assert channel == "task_progress_update", f"channel 应为 task_progress_update, 实际 {channel}"
    assert ws_payload["type"] == "task_progress"
    assert ws_payload["channel"] == "task_progress_update"
    assert ws_payload["ts"] == "2026-08-29T12:34:56"
    # data 字段透传原始 payload (前端 ws_dispatch._onTaskProgress 直接用)
    assert ws_payload["data"] == payload
    assert ws_payload["data"]["task_id"] == 14
    assert ws_payload["data"]["progress"]["phase"] == "running"


async def test_handle_message_missing_task_id_skipped(consumer, fake_broadcast):
    """payload 缺 task_id → ack + 0 broadcast (前端无法定位 task, 不推)"""
    payload = {"type": "task_progress_update", "status": "running", "progress": {"phase": "running"}}
    msg = FakeMessage(payload)

    await consumer._handle_message(msg)

    assert msg.acked
    assert fake_broadcast.calls == []


async def test_handle_message_invalid_json_skipped(consumer, fake_broadcast):
    """JSON 解析失败 → ack + 0 broadcast"""
    msg = FakeMessage("{invalid json}")

    await consumer._handle_message(msg)

    assert msg.acked
    assert fake_broadcast.calls == []


async def test_handle_message_non_dict_payload_skipped(consumer, fake_broadcast):
    """payload 不是 dict (e.g. JSON array) → ack + 0 broadcast"""
    msg = FakeMessage(json.dumps([1, 2, 3]))  # array, 不是 dict

    await consumer._handle_message(msg)

    assert msg.acked
    assert fake_broadcast.calls == []


async def test_handle_message_ws_broadcast_failure_still_acks(consumer, fake_broadcast):
    """ws broadcast 抛异常 → 仍 ack (best-effort, 避免消息积压)"""
    fake_broadcast.fail_first_n = 1
    payload = {"type": "task_progress_update", "task_id": 14, "status": "running"}
    msg = FakeMessage(payload)

    await consumer._handle_message(msg)

    # 异常被吞, 但仍 ack
    assert msg.acked
    assert len(fake_broadcast.calls) == 0  # 异常那次没收集到


async def test_handle_message_with_finished_status(consumer, fake_broadcast):
    """finished status payload → 正常 broadcast (前端拿到 task 进入完成态)"""
    payload = {
        "type": "task_progress_update",
        "task_id": 6,
        "status": "finished",
        "progress": {"phase": "done", "msg": "回测完成"},
        "ts": "2026-08-29T12:35:00",
    }
    msg = FakeMessage(payload)

    await consumer._handle_message(msg)

    assert msg.acked
    assert len(fake_broadcast.calls) == 1
    channel, ws_payload = fake_broadcast.calls[0]
    assert ws_payload["data"]["status"] == "finished"
    assert ws_payload["data"]["progress"]["phase"] == "done"


async def test_handle_message_with_only_progress_no_status(consumer, fake_broadcast):
    """只含 progress 不含 status 的 payload (phase-only update) → 仍 broadcast"""
    payload = {
        "type": "task_progress_update",
        "task_id": 14,
        "progress": {"phase": "build_cerebro", "msg": "构造引擎中"},
        "ts": "2026-08-29T12:34:00",
    }
    msg = FakeMessage(payload)

    await consumer._handle_message(msg)

    assert msg.acked
    assert len(fake_broadcast.calls) == 1
    _, ws_payload = fake_broadcast.calls[0]
    assert "status" not in ws_payload["data"]  # payload 本身没有 status
    assert ws_payload["data"]["progress"]["phase"] == "build_cerebro"


# ─────────────── Module-level singleton smoke ───────────────


async def test_get_task_progress_consumer_singleton(monkeypatch):
    """模块单例 — get_task_progress_consumer() 返同一实例"""
    from server.services.strategy.task_progress_consumer import (
        get_task_progress_consumer, reset_for_test,
    )

    reset_for_test()
    c1 = get_task_progress_consumer()
    c2 = get_task_progress_consumer()
    assert c1 is c2

    reset_for_test()
    c3 = get_task_progress_consumer()
    assert c3 is not c1, "reset 后应新建实例"