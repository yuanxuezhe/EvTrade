"""
server.services.strategy.task_progress_consumer — task_progress 实时推送消费

📌 订阅 RabbitMQ strategy.exchange/routing_key="task.progress.*"
   收到 1 条 task_progress 消息 → ws_manager.broadcast("task_progress_update", payload)

设计要点:
- aio_pika async consumer (独立 connection, 不与 signal_consumer 共用)
- 手动 ACK (处理成功才 ack, 防 consumer crash 丢消息)
- prefetch_count=20 (进度消息频率高, 限堆积)
- 不做幂等去重 (消息无 trace_id; progress 推送丢一条也无大碍, 下一条会覆盖)
- 启动: server/main.py lifespan on_event
- 停止: lifespan shutdown

拓扑 (与 strategy_exec/signal/task_progress_publisher.py 对称):
- exchange: 复用 strategy.exchange (topic, durable=True) — 与 signal_consumer 同 exchange
- queue: EvTrade.TaskProgress (durable, 独立 queue)
- routing_key: "task.progress.*" (topic, 与 signal 的 stock_code 路由键隔离)
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

import aio_pika
from aio_pika.abc import AbstractRobustConnection

from server.config import settings
from server.ws.manager import ws_manager

log = logging.getLogger(__name__)


TASK_PROGRESS_ROUTING_PATTERN = "task.progress.*"  # 订阅所有 task_progress 路由


class TaskProgressConsumer:
    """订阅 strategy.exchange/task.progress.* → ws_manager.broadcast task_progress_update"""

    def __init__(self) -> None:
        self._connection: Optional[AbstractRobustConnection] = None
        self._channel: Optional[aio_pika.abc.AbstractRobustChannel] = None
        self._queue: Optional[aio_pika.abc.AbstractQueue] = None
        self._consumer_tag: Optional[str] = None
        self._stopped = False

    async def start(self) -> None:
        """启动 consumer (FastAPI lifespan startup 中调用)"""
        if self._connection is not None and not self._connection.is_closed:
            log.info("[task_progress_consumer] already started")
            return

        # RabbitMQ connection
        self._connection = await aio_pika.connect_robust(settings.RABBITMQ_URL)
        self._channel = await self._connection.channel()
        await self._channel.set_qos(prefetch_count=20)

        # declare queue + bind
        self._queue = await self._channel.declare_queue(
            settings.STRATEGY_TASK_PROGRESS_QUEUE,
            durable=True,
        )
        exchange = await self._channel.declare_exchange(
            settings.STRATEGY_EXCHANGE_NAME,
            aio_pika.ExchangeType.TOPIC,
            durable=True,
        )
        await self._queue.bind(exchange, routing_key=TASK_PROGRESS_ROUTING_PATTERN)

        # consume
        self._consumer_tag = await self._queue.consume(self._handle_message)

        log.info(
            "[task_progress_consumer] started: exchange=%s queue=%s pattern=%s",
            settings.STRATEGY_EXCHANGE_NAME,
            settings.STRATEGY_TASK_PROGRESS_QUEUE,
            TASK_PROGRESS_ROUTING_PATTERN,
        )

    async def stop(self) -> None:
        """停止 consumer"""
        self._stopped = True
        if self._queue is not None and self._consumer_tag is not None:
            try:
                await self._queue.cancel(self._consumer_tag)
            except Exception:
                pass
        if self._connection is not None and not self._connection.is_closed:
            await self._connection.close()
        self._connection = None
        self._channel = None
        self._queue = None
        log.info("[task_progress_consumer] stopped")

    async def _handle_message(self, message: aio_pika.abc.AbstractIncomingMessage) -> None:
        """收 1 条 task_progress 消息 → ws_manager.broadcast

        payload schema (与 strategy_exec publisher 一致):
          {
            "type": "task_progress_update",
            "task_id": int,
            "status": "running" | "finished" | "failed" | "stopped" | None,
            "progress": {"phase": ..., "msg": ..., "bar_idx": N, "total_bars": M, ...} | None,
            "ts": "<ISO 时间>"
          }

        ws broadcast 格式 (兼容 ws-protocol REQ-WS-002):
          {
            "type": "task_progress",
            "channel": "task_progress_update",
            "ts": "<server 时间>",
            "data": {...payload...}
          }
        """
        try:
            payload: Dict[str, Any] = message.json()
        except Exception as e:
            log.warning("[task_progress_consumer] invalid JSON, ack and skip: %s", e)
            await message.ack()
            return

        if not isinstance(payload, dict):
            log.warning(
                "[task_progress_consumer] payload not dict (got %s), ack and skip",
                type(payload).__name__,
            )
            await message.ack()
            return

        task_id = payload.get("task_id")
        if task_id is None:
            log.warning(
                "[task_progress_consumer] payload missing task_id, ack and skip: %s",
                payload,
            )
            await message.ack()
            return

        # ws broadcast — data 字段塞原始 payload (前端 ws_dispatch.js _onTaskProgress 直接用)
        ws_payload = {
            "type": "task_progress",
            "channel": "task_progress_update",
            "ts": payload.get("ts"),
            "data": payload,
        }

        try:
            await ws_manager.broadcast("task_progress_update", ws_payload)
            log.debug(
                "[task_progress_consumer] broadcast task=%d status=%s phase=%s",
                task_id,
                payload.get("status"),
                (payload.get("progress") or {}).get("phase"),
            )
        except Exception as e:  # noqa: BLE001
            log.warning(
                "[task_progress_consumer] ws broadcast failed for task=%d: %s (ack anyway)",
                task_id, e,
            )

        # ack — 进度消息无幂等, 即便 ws 推失败也不重投 (避免积压)
        await message.ack()


# 模块级单例 + 启停包装
_consumer: Optional[TaskProgressConsumer] = None
_consumer_lock = asyncio.Lock()


def get_task_progress_consumer() -> TaskProgressConsumer:
    global _consumer
    if _consumer is None:
        _consumer = TaskProgressConsumer()
    return _consumer


async def start_task_progress_consumer() -> None:
    async with _consumer_lock:
        await get_task_progress_consumer().start()


async def stop_task_progress_consumer() -> None:
    async with _consumer_lock:
        if _consumer is not None:
            await _consumer.stop()


def reset_for_test() -> None:
    """测试用 — 清单例"""
    global _consumer
    _consumer = None