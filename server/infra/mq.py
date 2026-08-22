"""
infra/mq.py — aio_pika RMQ 长连接基类

职责：纯传输层基类 — RMQ 连接 / channel / exchange / queue declare / publish / 通用 listener。

不包含：
- pending future 管理（业务级，RPClient 持有）
- msg_id 匹配 reply（业务级，RPClient._handle_reply）
- 业务 dispatcher 编排（services/push/dispatcher.py）
- 协议常量（RABBITMQ_URL / EXCHANGE_NAME 等由 RPClient 持有）
"""
import asyncio
import logging
from typing import Awaitable, Callable, Optional

import aio_pika
from aio_pika import ExchangeType, Message

log = logging.getLogger(__name__)


class MessageQueueClient:
    """aio_pika RMQ 长连接基类（传输层本分）。

    子类负责：业务级 pending future 管理 / 业务 dispatcher 编排。
    本基类只暴露通用传输能力 + 通用 listener（回调 raw bytes 给上层）。
    """

    def __init__(self, url: str):
        self.url = url
        self.conn: Optional[aio_pika.Connection] = None
        self.channel: Optional[aio_pika.Channel] = None
        self.exchange: Optional[aio_pika.Exchange] = None
        self.reply_queue: Optional[aio_pika.Queue] = None
        self.push_queue: Optional[aio_pika.Queue] = None
        # publisher confirm 超时（防 broker 不 ack 时永久挂起）；子类可覆盖
        self.publish_confirm_timeout: float = 5.0

    async def connect(
        self,
        exchange_name: str,
        reply_queue_name: str,
        push_queue_name: str,
        request_queue_name: str,
        exchange_type: ExchangeType = ExchangeType.TOPIC,
        durable: bool = True,
    ) -> None:
        """建立 RMQ 长连接 + 声明 exchange + 声明 req/reply/push 队列 + 绑定。

        幂等守卫：已连接且未关闭 → 直接返回（避免 FastAPI 重启/双启动时重复 declare）。
        """
        if self.conn is not None and not self.conn.is_closed:
            log.debug("MessageQueueClient.connect: already connected, skip")
            return
        self.conn = await aio_pika.connect_robust(self.url)
        # publisher_confirms=True 让 publish() 等 broker ack，broker 重启/磁盘满不再静默丢包
        self.channel = await self.conn.channel(publisher_confirms=True)
        self.exchange = await self.channel.declare_exchange(
            exchange_name, exchange_type, durable=durable,
        )
        # request queue（broker 消费端订阅；publisher 仅按 routing_key 发布，不强需 declare 但对称声明便于排查）
        req_q = await self.channel.declare_queue(request_queue_name, durable=durable)
        await req_q.bind(self.exchange, routing_key=request_queue_name)
        # reply queue
        self.reply_queue = await self.channel.declare_queue(reply_queue_name, durable=durable)
        await self.reply_queue.bind(self.exchange, routing_key=reply_queue_name)
        # push queue
        self.push_queue = await self.channel.declare_queue(push_queue_name, durable=durable)
        await self.push_queue.bind(self.exchange, routing_key=push_queue_name)
        log.info(
            "MessageQueueClient connected, exchange=%s req=%s reply=%s push=%s (confirms=on)",
            exchange_name, request_queue_name, reply_queue_name, push_queue_name,
        )

    async def publish(
        self,
        wire_data: bytes,
        routing_key: str,
        timeout: Optional[float] = None,
    ) -> None:
        """发布到 exchange 指定 routing_key；publisher confirm 等待 broker ack。

        timeout=None 时使用 self.publish_confirm_timeout。
        超时抛 RuntimeError（调用方负责清理 pending 等业务级状态）。
        """
        if self.exchange is None:
            raise RuntimeError("MessageQueueClient.publish: exchange not initialized (call connect first)")
        if timeout is None:
            timeout = self.publish_confirm_timeout
        await asyncio.wait_for(
            self.exchange.publish(Message(body=wire_data), routing_key=routing_key),
            timeout=timeout,
        )

    async def listen_replies(
        self,
        on_message: Callable[[bytes], Awaitable[None]],
    ) -> None:
        """通用 reply queue listener — 把每条消息的 raw bytes 回调给 on_message。

        on_message 业务层实现（如 RPClient._handle_reply）负责 decode + 匹配 pending。
        """
        if not self.reply_queue:
            raise RuntimeError("MessageQueueClient.listen_replies: reply_queue not declared")
        log.info("MessageQueueClient reply listener started")
        async with self.reply_queue.iterator() as qiter:
            async for msg in qiter:
                async with msg.process():
                    await on_message(msg.body)

    async def listen_pushs(
        self,
        on_message: Callable[[bytes], Awaitable[None]],
    ) -> None:
        """通用 push queue listener — 把每条消息的 raw bytes 回调给 on_message。"""
        if not self.push_queue:
            raise RuntimeError("MessageQueueClient.listen_pushs: push_queue not declared")
        log.info("MessageQueueClient push listener started")
        async with self.push_queue.iterator() as qiter:
            async for msg in qiter:
                async with msg.process():
                    await on_message(msg.body)

    async def close(self) -> None:
        """关闭 RMQ 连接。"""
        if self.conn:
            await self.conn.close()
            self.conn = None
            self.channel = None
            self.exchange = None
            self.reply_queue = None
            self.push_queue = None
