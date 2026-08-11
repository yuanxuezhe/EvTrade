"""
strategy_exec.signal.types — Signal 数据类 + RabbitMQ payload 序列化

📌 Signal 是一次"买/卖信号"的不可变表示:
   - strategy_exec 引擎生成 Signal 对象
   - signal_publisher.publish_signal() 序列化为 JSON → RabbitMQ
   - EvTrade signal_consumer 反序列化 → POST /api/orders/place
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional


class SignalType(str, Enum):
    """信号类型 — 与 broker 委托方向解耦"""

    BUY = "BUY"
    SELL = "SELL"
    INFO = "INFO"  # 用户脚本仅记录, 不下单


@dataclass
class Signal:
    """一次交易信号的不可变表示"""

    task_id: int
    user_id: int
    script_id: str
    signal_type: SignalType
    stock_code: str
    price: float
    volume: int
    price_type: str = "limit"  # "limit" | "market"
    indicators: Dict[str, Any] = field(default_factory=dict)
    msg: str = ""
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    stime: str = ""  # 触发信号的 K 线时间 (YYYYMMDDHHMMSS), 空=未知
    mode: str = ""   # "backtest" | "live" (区分回测模拟信号 vs 实盘信号)
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    # v126: 策略下单母单归因 (signal_consumer 读 parent_task_id 写 orders.task_id)
    parent_task_id: Optional[int] = None  # strategy_order.task_id (None = 非母单)
    strategy_name: str = ""               # 子单 user_def 用

    def to_payload(self) -> Dict[str, Any]:
        """转 JSON-serializable dict (RabbitMQ payload)"""
        d = asdict(self)
        d["signal_type"] = self.signal_type.value  # enum → str
        return d


def signal_to_payload(signal: Signal) -> str:
    """Signal → JSON string (RabbitMQ message body)"""
    return json.dumps(signal.to_payload(), ensure_ascii=False, default=str)


def payload_to_signal(payload: Dict[str, Any]) -> Signal:
    """RabbitMQ payload dict → Signal (EvTrade 消费侧用)"""
    return Signal(
        task_id=int(payload["task_id"]),
        user_id=int(payload["user_id"]),
        script_id=str(payload["script_id"]),
        signal_type=SignalType(payload["signal_type"]),
        stock_code=str(payload["stock_code"]),
        price=float(payload["price"]),
        volume=int(payload["volume"]),
        price_type=str(payload.get("price_type", "limit")),
        indicators=payload.get("indicators", {}),
        msg=str(payload.get("msg", "")),
        ts=str(payload.get("ts", datetime.now(timezone.utc).isoformat())),
        stime=str(payload.get("stime", "")),
        mode=str(payload.get("mode", "")),
        trace_id=str(payload.get("trace_id", str(uuid.uuid4()))),
        parent_task_id=(
            int(payload["parent_task_id"]) if payload.get("parent_task_id") is not None else None
        ),
        strategy_name=str(payload.get("strategy_name", "")),
    )