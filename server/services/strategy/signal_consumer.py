"""
server/services/strategy/signal_consumer.py — EvTrade signal_consumer

📌 订阅 RabbitMQ strategy.exchange/EvTrade.StrategySignal
   收到 BUY/SELL signal → POST /api/orders/place (用 service JWT 鉴权)

设计要点:
- aio_pika async consumer (单连接, 独立 channel)
- 手动 ACK (处理成功才 ack, 防 consumer crash 丢 signal)
- prefetch_count=10 (限堆积)
- trace_id 幂等去重 (24h TTL)
- 启动: server/main.py lifespan on_event
- 停止: lifespan shutdown
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Set

import aio_pika
import httpx
from aio_pika.abc import AbstractRobustConnection

from server.config import settings

log = logging.getLogger(__name__)

PLACE_ORDER_URL = "/api/orders/place"  # EvTrade 内部相对路径 (self-call)
SIGNAL_DEDUP_TTL = 24 * 3600  # 24h


class SignalConsumer:
    """订阅 strategy.exchange/EvTrade.StrategySignal, 收 signal → POST /api/orders/place"""

    def __init__(self) -> None:
        self._connection: Optional[AbstractRobustConnection] = None
        self._channel: Optional[aio_pika.abc.AbstractRobustChannel] = None
        self._queue: Optional[aio_pika.abc.AbstractQueue] = None
        self._consumer_tag: Optional[str] = None
        self._processed_trace_ids: Set[str] = set()
        self._last_prune = datetime.now()
        # service token — 走 EvTrade JWT, 由 /grant (v92) 生成的永久 token
        self._service_token: Optional[str] = None
        self._http_client: Optional[httpx.AsyncClient] = None
        self._stopped = False

    async def start(self) -> None:
        """启动 consumer (在 FastAPI lifespan startup 中调用)"""
        if self._connection is not None and not self._connection.is_closed:
            log.info("[signal_consumer] already started")
            return

        # 加载 service token (EvTrade /grant 生成的永久 token)
        self._service_token = os.environ.get("EVTRADE_SERVICE_TOKEN", "")
        if not self._service_token:
            log.warning(
                "[signal_consumer] EVTRADE_SERVICE_TOKEN not set, "
                "will use shared admin token fallback"
            )
            self._service_token = os.environ.get("EVTRADE_ADMIN_TOKEN", "")

        # HTTP client (调自家 /api/orders/place)
        self._http_client = httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{settings.API_PORT}",
            timeout=10.0,
            headers={"Authorization": f"Bearer {self._service_token}"},
        )

        # RabbitMQ connection
        self._connection = await aio_pika.connect_robust(settings.RABBITMQ_URL)
        self._channel = await self._connection.channel()
        await self._channel.set_qos(prefetch_count=10)

        # declare queue (idempotent)
        self._queue = await self._channel.declare_queue(
            settings.STRATEGY_SIGNAL_QUEUE,
            durable=True,
        )
        # bind to strategy exchange
        exchange = await self._channel.declare_exchange(
            settings.STRATEGY_EXCHANGE_NAME,
            aio_pika.ExchangeType.TOPIC,
            durable=True,
        )
        await self._queue.bind(exchange, routing_key="*")  # 所有 stock_code

        # consume
        self._consumer_tag = await self._queue.consume(self._handle_message)

        log.info(
            "[signal_consumer] started: exchange=%s queue=%s",
            settings.STRATEGY_EXCHANGE_NAME,
            settings.STRATEGY_SIGNAL_QUEUE,
        )

    async def stop(self) -> None:
        """停止 consumer"""
        self._stopped = True
        if self._queue is not None and self._consumer_tag is not None:
            try:
                await self._queue.cancel(self._consumer_tag)
            except Exception:
                pass
        if self._http_client is not None:
            await self._http_client.aclose()
        if self._connection is not None and not self._connection.is_closed:
            await self._connection.close()
        self._connection = None
        self._channel = None
        self._queue = None
        log.info("[signal_consumer] stopped")

    async def _handle_message(self, message: aio_pika.abc.AbstractIncomingMessage) -> None:
        """收 1 条 signal message → 实时推前端 WS + (live BUY/SELL → POST /api/orders/place)"""
        try:
            payload = message.json()
        except Exception as e:
            log.warning("[signal_consumer] invalid JSON, ack and skip: %s", e)
            await message.ack()
            return

        trace_id = payload.get("trace_id", "")
        signal_type = payload.get("signal_type", "INFO")
        mode = payload.get("mode", "")

        # 幂等: 同一 trace_id 跳过 (避免 consumer 重启后重复下单)
        if trace_id and self._is_processed(trace_id):
            log.info("[signal_consumer] dup trace_id=%s, skip", trace_id)
            await message.ack()
            return

        # 实时推前端 (task_progress_update WS 频道) — 回测/实盘信号都推
        await self._broadcast_task_progress(payload)

        # 回测信号: 只记录 + 前端可见, 绝不下真实单
        #   (strategy_exec 回测也会 publish signal 到 MQ, mode='backtest' 标识)
        if mode == "backtest":
            log.info("[signal_consumer] backtest signal (no order): type=%s task=%d stock=%s trace=%s",
                     signal_type, payload.get("task_id"), payload.get("stock_code"), trace_id)
            self._mark_processed(trace_id)
            await message.ack()
            return

        # INFO 信号不触发下单, 仅记录
        if signal_type == "INFO":
            log.info("[signal_consumer] INFO signal (no order): trace=%s msg=%s",
                     trace_id, payload.get("msg", ""))
            self._mark_processed(trace_id)
            await message.ack()
            return

        log.info(
            "[signal_consumer] received: type=%s task=%d stock=%s price=%.2f vol=%d trace=%s",
            signal_type, payload.get("task_id"), payload.get("stock_code"),
            payload.get("price", 0), payload.get("volume", 0), trace_id,
        )

        # 转下单参数
        order_type = "23" if signal_type == "BUY" else "24"
        price_type = 44 if payload.get("price_type", "limit") == "market" else 11  # FIX
        try:
            await self._http_client.post(  # type: ignore[union-attr]
                PLACE_ORDER_URL,
                json={
                    "stock_code": payload.get("stock_code"),
                    "order_type": order_type,
                    "price_type": price_type,
                    "price": payload.get("price"),
                    "volume": payload.get("volume"),
                    "remark": f"strategy-{payload.get('task_id')}-{trace_id[:8]}",
                    "strategy_type": 1,  # 标记: 策略触发单 (v66+ 字段)
                },
            )
            self._mark_processed(trace_id)
            await message.ack()
            log.info("[signal_consumer] order placed: trace=%s", trace_id)
        except httpx.HTTPStatusError as e:
            log.error("[signal_consumer] place_order failed (HTTP %d): %s", e.response.status_code, e.response.text)
            # 400/422 业务错 → ack 不重试 (避免无效消息反复跑)
            # 5xx 服务错 → nack requeue=True 重试
            if 500 <= e.response.status_code < 600:
                await message.nack(requeue=True)
            else:
                self._mark_processed(trace_id)
                await message.ack()
        except Exception as e:
            log.exception("[signal_consumer] unexpected error: %s", e)
            await message.nack(requeue=True)

    async def _broadcast_task_progress(self, payload: Dict[str, Any]) -> None:
        """把 1 条 signal 实时推给前端 (task_progress_update WS 频道)

        前端 ws_dispatch._onTaskProgress → wsStore.lastTaskProgress → ScriptTask.vue
        实时插入信号流 + 更新进度。broadcast 失败绝不影响 MQ ack (非致命)。
        """
        try:
            from server.ws.manager import ws_manager
            await ws_manager.broadcast("task_progress_update", {
                "type": "task_progress_update",
                "data": {
                    "task_id": payload.get("task_id"),
                    "mode": payload.get("mode", ""),
                    "status": "running",
                    "signal": {
                        "signal_type": payload.get("signal_type"),
                        "stock_code": payload.get("stock_code"),
                        "price": payload.get("price"),
                        "volume": payload.get("volume"),
                        "msg": payload.get("msg", ""),
                        "stime": payload.get("stime", ""),
                        "indicators": payload.get("indicators", {}),
                        "ts": payload.get("ts", ""),
                        "trace_id": payload.get("trace_id", ""),
                        "mode": payload.get("mode", ""),
                    },
                },
            })
        except Exception as e:
            log.warning("[signal_consumer] ws broadcast failed (non-fatal): %s", e)

    def _is_processed(self, trace_id: str) -> bool:
        """检查 trace_id 是否已处理 (24h TTL)"""
        self._maybe_prune()
        return trace_id in self._processed_trace_ids

    def _mark_processed(self, trace_id: str) -> None:
        if trace_id:
            self._processed_trace_ids.add(trace_id)

    def _maybe_prune(self) -> None:
        """24h 清理一次"""
        now = datetime.now()
        if (now - self._last_prune) > timedelta(hours=1):
            # 简化: 满 24h 直接清空 (新一周期的去重窗口)
            if (now - self._last_prune) > timedelta(seconds=SIGNAL_DEDUP_TTL):
                self._processed_trace_ids.clear()
                self._last_prune = now


# 单例
_consumer: Optional[SignalConsumer] = None


def get_signal_consumer() -> SignalConsumer:
    global _consumer
    if _consumer is None:
        _consumer = SignalConsumer()
    return _consumer


async def start_signal_consumer() -> None:
    """在 FastAPI lifespan startup 中调用"""
    await get_signal_consumer().start()


async def stop_signal_consumer() -> None:
    """在 FastAPI lifespan shutdown 中调用"""
    await get_signal_consumer().stop()