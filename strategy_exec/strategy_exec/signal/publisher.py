"""
strategy_exec.signal.publisher — RabbitMQ Publisher with Publisher Confirms

📌 设计要点:
- 单连接 + channel pool (asyncio)
- publisher confirms 模式 (broker 收到后才返回)
- 失败重试 N 次 (exponential backoff)
- 推送失败抛 SignalPublishError (caller 处理)

拓扑 (与 EvTrade signal_consumer 约定):
- exchange: EVTRADE_STRATEGY_EXCHANGE_NAME (topic, durable=True)
- routing_key: stock_code (例 "600519.SH")
- consumer queue: EVTRADE_STRATEGY_SIGNAL_QUEUE
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

import aio_pika
from aio_pika.abc import AbstractRobustChannel, AbstractRobustConnection

from strategy_exec.config import get_settings
from strategy_exec.signal.types import Signal, signal_to_payload

log = logging.getLogger(__name__)


class SignalPublishError(Exception):
    """signal 推送失败 (broker confirm 超时/拒绝/连接错误)"""


class SignalPublisher:
    """异步 RabbitMQ publisher, 单例"""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._connection: Optional[AbstractRobustConnection] = None
        self._channel: Optional[AbstractRobustChannel] = None
        self._exchange: Optional[aio_pika.abc.AbstractExchange] = None
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        """连接到 RabbitMQ + 声明 exchange"""
        async with self._lock:
            if self._connection is not None and not self._connection.is_closed:
                return
            self._connection = await aio_pika.connect_robust(
                self.settings.evtrade_rabbitmq_url,
            )
            self._channel = await self._connection.channel(publisher_confirms=True)
            self._exchange = await self._channel.declare_exchange(
                self.settings.evtrade_strategy_exchange_name,
                aio_pika.ExchangeType.TOPIC,
                durable=True,
            )
            log.info(
                "[publisher] connected to %s, exchange=%s",
                self.settings.evtrade_rabbitmq_url,
                self.settings.evtrade_strategy_exchange_name,
            )

    async def close(self) -> None:
        if self._connection is not None and not self._connection.is_closed:
            await self._connection.close()
        self._connection = None
        self._channel = None
        self._exchange = None

    async def publish_signal(self, signal: Signal) -> str:
        """推送 1 条 signal. 成功返 trace_id (用于审计关联)

        失败: SignalPublishError (caller 处理 — 写 error_msg)
        """
        if self._exchange is None:
            await self.connect()

        body = signal_to_payload(signal).encode("utf-8")
        message = aio_pika.Message(
            body=body,
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            message_id=signal.trace_id,
            headers={
                "task_id": signal.task_id,
                "user_id": signal.user_id,
                "script_id": signal.script_id,
                "signal_type": signal.signal_type.value,
            },
        )

        retries = self.settings.evtrade_strategy_publish_retries
        last_exc: Optional[Exception] = None
        for attempt in range(1, retries + 1):
            try:
                assert self._exchange is not None
                await self._exchange.publish(
                    message,
                    routing_key=signal.stock_code,
                    timeout=self.settings.evtrade_strategy_publish_confirm_timeout,
                )
                log.info(
                    "[publisher] signal published task=%d type=%s stock=%s price=%.2f vol=%d trace=%s",
                    signal.task_id, signal.signal_type.value, signal.stock_code,
                    signal.price, signal.volume, signal.trace_id,
                )
                return signal.trace_id
            except (asyncio.TimeoutError, aio_pika.exceptions.AMQPException) as e:
                last_exc = e
                wait = 2 ** (attempt - 1)  # 1s, 2s, 4s
                log.warning(
                    "[publisher] publish failed (attempt %d/%d), retry in %ds: %s",
                    attempt, retries, wait, e,
                )
                if attempt < retries:
                    await asyncio.sleep(wait)

        raise SignalPublishError(
            f"publish failed after {retries} retries: {last_exc}"
        )


# 单例
_publisher: Optional[SignalPublisher] = None


def get_publisher() -> SignalPublisher:
    """返单例 (lazy init)"""
    global _publisher
    if _publisher is None:
        _publisher = SignalPublisher()
    return _publisher


async def close_publisher() -> None:
    """应用关闭时调用"""
    global _publisher
    if _publisher is not None:
        await _publisher.close()
        _publisher = None