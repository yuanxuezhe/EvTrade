"""
test_signal_consumer_v126.py — signal_consumer v126 归因 + strategy_type=2 单测

覆盖:
- BUY signal (mode=live, parent_task_id=42, strategy_name='s1') → 下单请求 task_id=42, user_def='s1', strategy_type=2
- 回测 signal (mode=backtest) → 跳过 (不下单)
- INFO signal → 跳过
- 决策 (D): live signal + parent_task_id=None → ack 不重试, 不下发下单请求
- 旧 v66/v123 path (无 mode 字段, parent_task_id 缺) → task_id=None, strategy_type=1 (默认旧行为)

不连真实 RabbitMQ, 用 _handle_message 直接喂 payload, monkeypatch
_http_client.post 记录下发请求。
"""
from __future__ import annotations

import asyncio
import os
import sys
from typing import Any, Dict, List

import pytest

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.insert(0, _PROJECT_ROOT)
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "server"))

from server.services.strategy.signal_consumer import SignalConsumer  # noqa: E402


class FakeIncomingMessage:
    """模拟 aio_pika AbstractIncomingMessage — 喂 payload + 追踪 ack/nack."""

    def __init__(self, payload: Dict[str, Any]) -> None:
        self._payload = payload
        self.acked = False
        self.nacked_requeue: Any = None

    def json(self) -> Dict[str, Any]:
        return self._payload

    async def ack(self) -> None:
        self.acked = True

    async def nack(self, requeue: bool = False) -> None:
        self.nacked_requeue = requeue


def _make_consumer_with_capture() -> tuple[SignalConsumer, List[Dict[str, Any]]]:
    """构造 SignalConsumer 但不连 MQ, monkeypatch _http_client.post 捕获下单请求."""
    c = SignalConsumer()
    captured: List[Dict[str, Any]] = []

    class FakeClient:
        async def post(self, url, json=None, **kwargs):
            captured.append({"url": url, "json": json})
            class R:
                status_code = 200
                text = "ok"
            return R()

    c._http_client = FakeClient()  # type: ignore[assignment]
    return c, captured


def _payload(**overrides) -> Dict[str, Any]:
    defaults = {
        "task_id": 1,
        "user_id": 7,
        "script_id": "x",
        "signal_type": "BUY",
        "stock_code": "600519.SH",
        "price": 100.0,
        "volume": 100,
        "price_type": "limit",
        "msg": "",
        "ts": "2026-08-11T10:00:00Z",
        "stime": "",
        "mode": "live",
        "trace_id": "trace-ut-1",
        "parent_task_id": 42,
        "strategy_name": "均线策略",
    }
    defaults.update(overrides)
    return defaults


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_buy_signal_v126_attribution():
    """BUY live signal + parent_task_id + strategy_name → 下单请求带归因."""
    c, captured = _make_consumer_with_capture()
    msg = FakeIncomingMessage(_payload())

    _run(c._handle_message(msg))

    assert msg.acked
    assert msg.nacked_requeue is None
    assert len(captured) == 1
    body = captured[0]["json"]
    assert body["task_id"] == 42
    assert body["user_def"] == "均线策略"
    assert body["strategy_type"] == 2


def test_sell_signal_v126_attribution():
    c, captured = _make_consumer_with_capture()
    msg = FakeIncomingMessage(_payload(
        signal_type="SELL", parent_task_id=99, strategy_name="策略B",
    ))

    _run(c._handle_message(msg))

    assert msg.acked
    body = captured[0]["json"]
    assert body["order_type"] == "24"
    assert body["task_id"] == 99
    assert body["user_def"] == "策略B"
    assert body["strategy_type"] == 2


def test_backtest_signal_skipped():
    """回测 mode → 跳过 (不下单), ack."""
    c, captured = _make_consumer_with_capture()
    msg = FakeIncomingMessage(_payload(mode="backtest", parent_task_id=42))

    _run(c._handle_message(msg))

    assert msg.acked
    assert captured == []


def test_info_signal_skipped():
    """INFO 信号不触发下单."""
    c, captured = _make_consumer_with_capture()
    msg = FakeIncomingMessage(_payload(signal_type="INFO"))

    _run(c._handle_message(msg))

    assert msg.acked
    assert captured == []


def test_live_signal_missing_parent_task_id_acked_no_retry():
    """决策 (D): live signal + parent_task_id=None → 业务错, ack 不重试, 不下发."""
    c, captured = _make_consumer_with_capture()
    msg = FakeIncomingMessage(_payload(mode="live", parent_task_id=None))

    _run(c._handle_message(msg))

    assert msg.acked
    assert msg.nacked_requeue is None
    assert captured == []


def test_v66_v123_legacy_signal_default():
    """旧 v66/v123 path: 无 mode 字段, 无 parent_task_id → strategy_type=1 默认行为."""
    c, captured = _make_consumer_with_capture()
    legacy = _payload()
    legacy.pop("mode", None)
    legacy.pop("parent_task_id", None)
    legacy.pop("strategy_name", None)
    msg = FakeIncomingMessage(legacy)

    _run(c._handle_message(msg))

    assert msg.acked
    assert len(captured) == 1
    body = captured[0]["json"]
    assert body["task_id"] is None
    assert body["user_def"] == ""
    assert body["strategy_type"] == 1


def test_market_price_type():
    """price_type=market → POST price_type=44."""
    c, captured = _make_consumer_with_capture()
    msg = FakeIncomingMessage(_payload(price_type="market"))

    _run(c._handle_message(msg))

    assert msg.acked
    assert captured[0]["json"]["price_type"] == 44
