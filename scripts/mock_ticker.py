#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mock ticker — 独立行情模拟工具
=============================

用途：当 RabbitMQ 上游 / QMT publisher 没数据时，本工具 publish 模拟 tick
      到 RabbitMQ `quota.exchange`（FANOUT, routing_key=stock_code），使
      hqserver 能消费到 tick 进而广播给 backend quote_consumer，最终驱动
      前端 Holdings / Trade 页面行情更新（含 subscribe 协议 + 严格过滤路径）。

架构位置：
  mock_ticker ──RabbitMQ publish──> quota.exchange
                                      │
                                      ↓ FANOUT（实际 hqserver 绑队列 EvQuota 消费）
                                    hqserver.consumer
                                      │
                                      ├─broadcast_exchange.publish → quota.broadcast.exchange
                                      └─_broadcast_ws → ws://backend.quote_consumer
                                                       │
                                                       └─_fanout_tick → broadcast_to_stock
                                                                        │
                                                                        ↓ 严格按订阅过滤
                                                                      frontend WS

数据格式（与 hq/hqserver.py:165-208 一致）：
  - RabbitMQ body: bytes（GBK 编码的 pipe-delimited 字符串）
  - 31 字段索引对应 server/services/strategy/quote_consumer.py:166-176
  - 每条 tick 可以是单行，也可以多条 tick 用 \\n 合并成一条消息
    （2026-07-09 quote-batch-split: QMT publisher 现在用 \\n 合并）

使用：
  python scripts/mock_ticker.py                       # 默认 5 tick/s, 默认股票池
  python scripts/mock_ticker.py --rate 20             # 20 tick/s
  python scripts/mock_ticker.py --codes 600519.SH,300750.SZ
  python scripts/mock_ticker.py --price-base 1820     # 指定基准价
  python scripts/mock_ticker.py --duration 30         # 跑 30 秒后退出
  python scripts/mock_ticker.py --batch-size 5        # 每次合并 5 条 tick 发
  python scripts/mock_ticker.py --url amqp://192.168.10.2:5672/

历史：2026-07-09 创建 — QMT publisher 不发数据期间，给前端行情页提供测试源。
"""
import argparse
import asyncio
import logging
import random
import signal
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional

try:
    import aio_pika
except ImportError:
    print("ERROR: aio_pika not installed. Run: pip install aio_pika", file=sys.stderr)
    sys.exit(1)


# ==================== 配置 ====================

# 默认股票池（A 股常见大盘股 + 用户测试过的）
DEFAULT_STOCKS = [
    "600519.SH",  # 贵州茅台
    "300750.SZ",  # 宁德时代
    "002594.SZ",  # 比亚迪
    "600036.SH",  # 招商银行
    "000858.SZ",  # 五粮液
    "601318.SH",  # 中国平安
    "600276.SH",  # 恒瑞医药
    "000333.SZ",  # 美的集团
    "601012.SH",  # 隆基绿能
    "002475.SZ",  # 立讯精密
    "603290.SH",  # 斯达半导（用户测试）
    "300947.SZ",  # 德必集团（用户测试）
    "002380.SZ",  # 科远智慧（用户测试）
    "563300.SH",  # 300ETF（用户测试）
]

# 各股票基准价
BASE_PRICES = {
    "600519.SH": 1820.0,
    "300750.SZ": 240.0,
    "002594.SZ": 280.0,
    "600036.SH": 38.5,
    "000858.SZ": 165.0,
    "601318.SH": 52.0,
    "600276.SH": 48.0,
    "000333.SZ": 72.0,
    "601012.SH": 18.5,
    "002475.SZ": 42.0,
    "603290.SH": 105.0,
    "300947.SZ": 28.0,
    "002380.SZ": 32.0,
    "563300.SH": 3.85,
}


# ==================== Logging ====================
log = logging.getLogger("mock_ticker")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)


# ==================== 核心 ====================


class MockTicker:
    """Mock ticker — publish 模拟 tick 到 RabbitMQ quota.exchange"""

    def __init__(
        self,
        url: str = "amqp://192.168.10.2:5672/",
        exchange_name: str = "quota.exchange",
        stock_codes: List[str] = None,
        rate: float = 5.0,
        duration: int = 0,  # 0 = 永久
        price_base: Optional[float] = None,
        volatility: float = 0.002,
        batch_size: int = 1,  # 每次合并几条 tick 用 \n 发
        seed: Optional[int] = None,
    ):
        self.url = url
        self.exchange_name = exchange_name  # 默认 quota.exchange (兼容性保留，但实际 publish 到 default exchange + routing_key=queue_name)
        self.queue_name = "EvQuota"  # hqserver 监听的实际队列名
        self.stock_codes = stock_codes or DEFAULT_STOCKS
        self.rate = rate
        self.duration = duration
        self.volatility = volatility
        self.batch_size = batch_size

        # 初始价格
        if seed is not None:
            random.seed(seed)
        self.prices: Dict[str, float] = {}
        for code in self.stock_codes:
            base = (
                price_base if price_base is not None else BASE_PRICES.get(code, 50.0)
            )
            self.prices[code] = base * (1 + random.uniform(-0.02, 0.02))

        self.volumes: Dict[str, int] = {code: 0 for code in self.stock_codes}

        # 控制
        self._stop = asyncio.Event()
        self._sent = 0
        self._start_ts = None
        self._connection: Optional[aio_pika.RobustConnection] = None
        self._channel: Optional[aio_pika.RobustChannel] = None
        self._exchange: Optional[aio_pika.Exchange] = None

    def request_stop(self):
        """Ctrl-C / 信号触发"""
        self._stop.set()

    def _gen_tick_bytes(self, stock_code: str) -> bytes:
        """生成一条 tick 的 GBK pipe-delimited bytes（对应 hqserver 期望）"""
        # 1. 价格随机游走
        last_price = self.prices[stock_code]
        change_pct = random.gauss(0, self.volatility)
        new_price = last_price * (1 + change_pct)
        new_price = max(last_price * 0.95, min(last_price * 1.05, new_price))
        self.prices[stock_code] = new_price

        # 2. 当日开高低收
        base = BASE_PRICES.get(stock_code, last_price)
        open_p = base * (1 + random.uniform(-0.01, 0.01))
        high_p = max(open_p, last_price, new_price) * (1 + abs(random.gauss(0, 0.001)))
        low_p = min(open_p, last_price, new_price) * (1 - abs(random.gauss(0, 0.001)))
        prev_close = base

        # 3. 累计成交量
        self.volumes[stock_code] += random.randint(100, 10000)
        volume = self.volumes[stock_code]
        amount = volume * new_price
        openInt = random.randint(0, 100000)
        transactionNum = random.randint(0, 10000)

        # 4. 买卖五档
        spread = new_price * 0.001
        ask_prices = [new_price + spread * (i + 1) for i in range(5)]
        bid_prices = [new_price - spread * (i + 1) for i in range(5)]
        ask_vols = [random.randint(100, 5000) for _ in range(5)]
        bid_vols = [random.randint(100, 5000) for _ in range(5)]

        # 5. datetime
        now = datetime.now()
        dt_str = now.strftime("%Y%m%d%H%M%S") + f".{now.microsecond // 1000:03d}"

        # 6. 31 字段（索引对应 _parse_tick 注释）
        fields = [
            stock_code,
            dt_str,
            f"{new_price:.3f}",
            f"{open_p:.3f}",
            f"{high_p:.3f}",
            f"{low_p:.3f}",
            f"{prev_close:.3f}",
            str(volume),
            f"{amount:.2f}",
            str(openInt),
            str(transactionNum),
            *[f"{p:.3f}" for p in ask_prices],
            *[f"{p:.3f}" for p in bid_prices],
            *[str(v) for v in ask_vols],
            *[str(v) for v in bid_vols],
        ]

        # 7. body — GBK pipe-delimited
        body = "|".join(fields)
        return body.encode("gbk", errors="replace")

    async def _connect(self):
        """建立 RabbitMQ 长连接
        2026-07-09 修正：publish 用 default exchange + routing_key=EvQuota（与上游 QMT publisher 一致）
        之前 publish 到自建 FANOUT exchange quota.exchange 但 hqserver 已用 declare_queue
        （passive=False），消息没进 EvQuota 队列（被另一个不存在的 exchange 收走）
        """
        log.info("connecting to RabbitMQ: %s", self.url)
        self._connection = await aio_pika.connect_robust(self.url)
        self._channel = await self._connection.channel(publisher_confirms=False)
        # 不声明 exchange，直接用 default exchange
        log.info("connected, will publish to default exchange with routing_key='%s'", self.queue_name)

    async def _close(self):
        """关闭连接"""
        try:
            if self._connection is not None:
                await self._connection.close()
        except Exception as e:
            log.warning("close error: %s", e)

    async def _send_loop(self):
        """按 rate 频率循环发 tick（支持 batch 合并）"""
        interval = 1.0 / self.rate
        i = 0
        while not self._stop.is_set():
            # 生成 batch_size 条 tick
            tick_lines = []
            for _ in range(self.batch_size):
                stock = self.stock_codes[i % len(self.stock_codes)]
                tick_bytes = self._gen_tick_bytes(stock)
                tick_lines.append(tick_bytes)
                i += 1

            # batch 合并（用 \n 分割，对应 2026-07-09 quote-batch-split）
            if len(tick_lines) == 1:
                body = tick_lines[0]
            else:
                body = b"\n".join(tick_lines)

            # publish（default exchange, routing_key=EvQuota）
            try:
                await self._channel.default_exchange.publish(
                    aio_pika.Message(
                        body=body,
                        delivery_mode=aio_pika.DeliveryMode.NOT_PERSISTENT,
                        content_type="application/octet-stream",
                    ),
                    routing_key=self.queue_name,
                )
                self._sent += len(tick_lines)
            except Exception as e:
                log.error("publish failed: %s", e)
                await asyncio.sleep(1)  # 退避

            # 进度日志（每 50 条）
            if self._sent % 50 < self.batch_size:
                log.info("sent %d ticks so far...", self._sent)

            await asyncio.sleep(interval)

    async def run(self):
        """主入口"""
        self._start_ts = time.time()
        log.info(
            "starting: stocks=%d rate=%.1f/s batch=%d duration=%s exchange=%s",
            len(self.stock_codes),
            self.rate,
            self.batch_size,
            f"{self.duration}s" if self.duration else "forever",
            self.exchange_name,
        )

        try:
            await self._connect()
            if self.duration:
                try:
                    await asyncio.wait_for(self._send_loop(), timeout=self.duration)
                except asyncio.TimeoutError:
                    log.info("duration reached, stopping")
            else:
                await self._send_loop()
        except Exception as e:
            log.error("run error: %s", e)
        finally:
            await self._close()
            elapsed = time.time() - self._start_ts
            log.info(
                "done — sent %d ticks in %.1fs (rate=%.1f/s)",
                self._sent,
                elapsed,
                self._sent / max(elapsed, 0.001),
            )


# ==================== CLI ====================


def parse_args():
    p = argparse.ArgumentParser(
        description="Mock ticker — 模拟 QMT publisher publish 行情到 RabbitMQ"
    )
    p.add_argument(
        "--url",
        default="amqp://192.168.10.2:5672/",
        help="RabbitMQ URL（默认 amqp://192.168.10.2:5672/）",
    )
    p.add_argument(
        "--exchange",
        default=None,
        help="已废弃：本工具直接 publish 到 default exchange + routing_key=EvQuota（与上游 QMT publisher 一致）",
    )
    p.add_argument(
        "--codes",
        default=None,
        help="股票代码列表，逗号分隔（默认 DEFAULT_STOCKS）",
    )
    p.add_argument(
        "--rate",
        type=float,
        default=5.0,
        help="发送速率 tick/s（默认 5.0）",
    )
    p.add_argument(
        "--duration",
        type=int,
        default=0,
        help="运行时长秒（0=永久，默认 0）",
    )
    p.add_argument(
        "--price-base",
        type=float,
        default=None,
        help="统一基准价（默认用 BASE_PRICES）",
    )
    p.add_argument(
        "--volatility",
        type=float,
        default=0.002,
        help="价格波动率（默认 0.002 = 0.2%）",
    )
    p.add_argument(
        "--batch-size",
        type=int,
        default=1,
        help="每条消息合并几条 tick 用 \\n（默认 1，对应 quote-batch-split）",
    )
    p.add_argument(
        "--seed",
        type=int,
        default=None,
        help="随机种子（默认 None）",
    )
    return p.parse_args()


async def main():
    args = parse_args()

    stock_codes = None
    if args.codes:
        stock_codes = [c.strip() for c in args.codes.split(",") if c.strip()]

    ticker = MockTicker(
        url=args.url,
        exchange_name=args.exchange,
        stock_codes=stock_codes,
        rate=args.rate,
        duration=args.duration,
        price_base=args.price_base,
        volatility=args.volatility,
        batch_size=args.batch_size,
        seed=args.seed,
    )

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, ticker.request_stop)

    await ticker.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("interrupted")
        sys.exit(0)