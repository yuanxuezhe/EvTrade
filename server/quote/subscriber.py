"""EvTrade 行情订阅：把 RabbitMQ 广播的行情包透传到 WebSocket。

参考 `hq/hqserver.py` / `hq/hqsuber.py` 的逻辑：
  - 后端作为 client，连接到 RabbitMQ
  - 声明一个 exclusive 临时队列
  - bind 到 `quota.broadcast.exchange`，用 `*.SH` / `*.SZ` 通配订阅全部 A 股
  - 每收到一条消息 → 通过 `ws_manager.broadcast('quote_update', payload)` 推给前端

不解析 body 字段：hqserver 现在发的格式是 `gbk` 编码 `stock_code|...|...` 分隔，
未来字段不固定，前端用 routing_key 作 stock_code 索引，body 原文转 JSON 字符串占位。
"""
import asyncio
from typing import Optional

import aio_pika
from aio_pika import ExchangeType

from ws.manager import ws_manager

# 与 hq/hqserver.py 保持一致
RABBITMQ_URL = "amqp://192.168.10.2:5672/"
BROADCAST_EXCHANGE = "quota.broadcast.exchange"
WS_CHANNEL = "quote_update"

# A 股通配：上交所 *.SH / 深交所 *.SZ
SUBSCRIBE_PATTERNS = ["*.SH", "*.SZ"]


class QuoteSubscriber:
    def __init__(self, url: str = RABBITMQ_URL):
        self.url = url
        self.conn: Optional[aio_pika.Connection] = None
        self.channel: Optional[aio_pika.Channel] = None
        self._task: Optional[asyncio.Task] = None
        self._stopped = False

    async def start(self):
        if self._task and not self._task.done():
            return
        self._stopped = False
        self._task = asyncio.ensure_future(self._run())

    async def stop(self):
        self._stopped = True
        if self.conn and not self.conn.is_closed:
            try:
                await self.conn.close()
            except Exception as e:
                print(f"[QuoteSub] close error: {e}")
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=2.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._task.cancel()
            except Exception:
                pass
            self._task = None

    async def _run(self):
        """主循环：连接 → bind → 消费 → 转发。断线自动重连。"""
        backoff = 1.0
        while not self._stopped:
            try:
                print(f"[QuoteSub] connecting to {self.url}...")
                self.conn = await aio_pika.connect_robust(self.url)
                self.channel = await self.conn.channel()
                # 与 hqsuber 一致：exclusive 临时队列，连接断即销毁
                queue = await self.channel.declare_queue(exclusive=True)
                exchange = await self.channel.declare_exchange(
                    BROADCAST_EXCHANGE,
                    type=ExchangeType.TOPIC,
                    durable=True,
                    passive=True,
                )
                for pat in SUBSCRIBE_PATTERNS:
                    await queue.bind(exchange, routing_key=pat)
                    print(f"[QuoteSub] bound pattern {pat!r} on {BROADCAST_EXCHANGE}")

                print(f"[QuoteSub] listening → ws channel {WS_CHANNEL!r}")
                backoff = 1.0  # 连接成功，重置退避

                async with queue.iterator() as qiter:
                    async for amqp_msg in qiter:
                        if self._stopped:
                            break
                        stock_code = amqp_msg.routing_key or ""
                        try:
                            body_text = amqp_msg.body.decode("gbk", errors="replace")
                        except Exception as e:
                            body_text = f"<decode error: {e}>"
                        fields = body_text.split("|")
                        # 简单尝试解析最新价（如果 body 是 "code|ts|price|..." 格式）
                        last_price = _try_parse_price(fields)
                        payload = {
                            "type": "quote",
                            "channel": WS_CHANNEL,
                            "data": {
                                "stock_code": stock_code,
                                "last_price": last_price,
                                "fields": fields,
                                "body": body_text,
                            },
                        }
                        try:
                            await ws_manager.broadcast(WS_CHANNEL, payload)
                        except Exception as e:
                            print(f"[QuoteSub] broadcast error: {e}")
                        # 必须 ack，否则 AMQP 会无限重投（虽然 exclusive 队列不影响持久化）
                        try:
                            await amqp_msg.ack()
                        except Exception:
                            pass
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[QuoteSub] loop error: {type(e).__name__}: {e}; retry in {backoff}s")
                try:
                    if self.conn and not self.conn.is_closed:
                        await self.conn.close()
                except Exception:
                    pass
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

        print("[QuoteSub] stopped")


def _try_parse_price(fields) -> Optional[float]:
    """body 格式（31 字段，broker 实测）: `stock_code|datetime|...|...|...`
    index 0  = stock_code
    index 1  = yyyyMMddHHmmss.sss
    index 2  = 最新价
    后续字段含义：open / high / low / prev_close / volume / amount / ...
    由于厂商字段顺序尚未文档化，前端按索引取值，错了再调整。
    """
    if not fields or len(fields) < 3:
        return None
    try:
        return float(fields[2])
    except (ValueError, TypeError):
        return None


# ---- 单例 ----------------------------------------------------------------

_subscriber: Optional[QuoteSubscriber] = None


async def start_subscriber():
    global _subscriber
    if _subscriber is None:
        _subscriber = QuoteSubscriber()
    await _subscriber.start()


async def stop_subscriber():
    global _subscriber
    if _subscriber is not None:
        await _subscriber.stop()
        _subscriber = None