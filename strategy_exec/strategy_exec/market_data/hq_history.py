"""
strategy_exec.market_data.hq_history — 拉历史 K 线 (broker his_hq)

📌 broker his_hq 是 xtquant 的 RabbitMQ 通道, 同 EvTrade broker RPC:
   - exchange: quota_his.exchange (topic)
   - req_queue: EvTrade.ReqHisHq (rpc client 端)
   - 协议: msgpacket 格式 (Requester 返 Reply)

策略_exec 与 EvTrade 共享 broker, 走同一 RabbitMQ URL
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

import aio_pika
from aio_pika.abc import AbstractRobustConnection

from strategy_exec.config import get_settings

log = logging.getLogger(__name__)


class HQHistoryError(Exception):
    """拉历史 K 线失败"""


class HQHistoryClient:
    """async client for broker his_hq (单连接, 复用 channel)"""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._connection: Optional[AbstractRobustConnection] = None
        self._channel: Optional[aio_pika.abc.AbstractRobustChannel] = None

    async def connect(self) -> None:
        if self._connection is not None and not self._connection.is_closed:
            return
        self._connection = await aio_pika.connect_robust(self.settings.evtrade_rabbitmq_url)
        self._channel = await self._connection.channel()
        # declare reply queue (per-request)
        await self._channel.declare_queue(
            self.settings.evtrade_his_hq_req_queue,
            durable=True,
        )
        log.info("[hq_history] connected, queue=%s", self.settings.evtrade_his_hq_req_queue)

    async def close(self) -> None:
        if self._connection is not None and not self._connection.is_closed:
            await self._connection.close()
        self._connection = None
        self._channel = None

    async def fetch_bars(
        self,
        stock_code: str,
        start_date: str,  # YYYYMMDD
        end_date: str,    # YYYYMMDD
        period: str = "1d",
        fields: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """拉历史 K 线, 返 list of dict [{stime, open, high, low, close, volume, ...}]"""
        await self.connect()
        assert self._channel is not None

        if fields is None:
            fields = ["open", "high", "low", "close", "volume"]

        # msgpacket 风格 request payload (简化 — 真实协议由 broker 定义)
        request_id = str(uuid.uuid4())
        request_payload = {
            "func": "query_history_k_line",
            "request_id": request_id,
            "stock_code": stock_code,
            "period": period,
            "start_date": start_date,
            "end_date": end_date,
            "fields": fields,
        }

        # 监听 reply (reply_to 临时 queue)
        reply_queue = await self._channel.declare_queue(exclusive=True)
        routing_key = f"{self.settings.evtrade_his_hq_req_queue}.reply.{request_id}"

        async with reply_queue.iterator(timeout=self.settings.evtrade_his_hq_req_timeout) as it:
            # publish request
            exchange = await self._channel.declare_exchange(
                self.settings.evtrade_his_hq_exchange_name,
                aio_pika.ExchangeType.TOPIC,
                durable=True,
            )
            await exchange.publish(
                aio_pika.Message(
                    body=json.dumps(request_payload).encode("utf-8"),
                    reply_to=routing_key,
                    correlation_id=request_id,
                ),
                routing_key=self.settings.evtrade_his_hq_req_queue,
            )

            # wait reply
            async for msg in it:
                async with msg.process():
                    payload = json.loads(msg.body.decode("utf-8"))
                    if payload.get("request_id") != request_id:
                        continue
                    if payload.get("code", 0) != 0:
                        raise HQHistoryError(
                            f"broker his_hq error: code={payload.get('code')} msg={payload.get('msg')}"
                        )
                    bars = payload.get("bars", [])
                    log.info("[hq_history] fetched %d bars for %s %s~%s",
                             len(bars), stock_code, start_date, end_date)
                    return bars

        raise HQHistoryError(f"his_hq reply timeout ({self.settings.evtrade_his_hq_req_timeout}s)")


# 单例
_client: Optional[HQHistoryClient] = None


def get_hq_history_client() -> HQHistoryClient:
    global _client
    if _client is None:
        _client = HQHistoryClient()
    return _client


async def fetch_his_bars(
    stock_code: str,
    start_date: str,
    end_date: str,
    period: str = "1d",
    fields: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """便捷函数 (单例)"""
    return await get_hq_history_client().fetch_bars(stock_code, start_date, end_date, period, fields)


async def close_hq_history() -> None:
    global _client
    if _client is not None:
        await _client.close()
        _client = None