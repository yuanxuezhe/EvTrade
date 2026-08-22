"""
strategy — quote_consumer 后端 WS 客户端（行情快照 + 前端推送）

核心职责:
- 连接 hqserver WebSocket (默认 ws://127.0.0.1:8765)
- 解析 tick → 写 quote_cache (内存快照, 持久化由 main.py periodic flush task 负责)
- broadcast_to_stock 推前端 WS /ws/quote_update (行情面板实时刷新)

批量 flush (quote-batch-flush):
- 累积 tick 入 buffer 后 flush 触发: 50 条 OR 1 秒 (双阈值)
- 不做股票级去重 - 同窗口内同股票多 tick 全部保留 (用户要求看到每一根 tick)
- 前端 ws payload 格式不变 (单 tick), 但 1 个 ws frame 装 N 条 tick
- 仍走 broadcast_to_stock 按订阅过滤 (前端 ws payload 格式不变)

📌 指数退避重连 1s → 2s → 4s → ... → 30s 上限
📌 60s 无 tick → warn log (连接是活的, 行情低谷不重连)
📌 30s 心跳 log 累计 tick 数
📌 Singleton 模式: module-level _quote_consumer + get/close 函数
"""
import asyncio
import json
import logging
import time
from typing import Dict, Optional, List

from server.cache.quote_cache import get_quote_cache as _get_quote_cache
from server.ws.manager import ws_manager  # 让前端 /ws/quote_update 也能收到 tick

# 模块级 cache 单例
quote_cache = _get_quote_cache()

log = logging.getLogger(__name__)


class QuoteConsumer:
    """hqserver → 行情缓存 / 前端 WS fan-out

    📌 生命周期：start() → connect_loop + consume_loop + health_loop
                 stop() → _stop.set() + ws.close()
    📌 主循环内部用 asyncio.gather 同时跑 consume_loop + health_loop，断连时 gather 自动取消
    """

    # 指数退避参数
    RECONNECT_INITIAL = 1.0
    RECONNECT_MAX = 30.0
    # 健康检查参数
    HEALTH_INTERVAL = 30.0
    NO_TICK_WARN = 60.0

    def __init__(self, url: str):
        self.url = url
        self._latest_price: Dict[str, float] = {}
        self._stop = asyncio.Event()
        self._ws = None
        self._last_tick_ts: Optional[float] = None
        self._tick_count: int = 0
        # 批量 flush: 累积 N tick 后 flush 触发 (50条 / 1秒)
        # 不去重, 同股票多 tick 全部保留
        from server.config import settings
        self._batch_max: int = settings.QUOTE_BATCH_MAX
        self._batch_flush_ms: int = settings.QUOTE_BATCH_FLUSH_MS
        self._batch_buf: List[dict] = []  # 改为 list, 保留每一根 tick
        self._batch_lock = asyncio.Lock()
        self._last_flush_ts: float = time.time()
        self._flusher_task: Optional[asyncio.Task] = None

    # ── 生命周期 ──

    async def start(self) -> None:
        """入口：启动主循环（永久直到 stop）"""
        log.info("quote_consumer starting: url=%s batch_max=%d flush_ms=%d",
                 self.url, self._batch_max, self._batch_flush_ms)
        # 启动定时 flush 后台 task (1秒兜底, 防止慢市累计)
        self._flusher_task = asyncio.ensure_future(self._flusher_loop())
        await self._main_loop()

    async def stop(self) -> None:
        """置停止信号 + 关 ws"""
        log.info("quote_consumer stopping...")
        self._stop.set()
        if self._flusher_task and not self._flusher_task.done():
            self._flusher_task.cancel()
            try:
                await self._flusher_task
            except asyncio.CancelledError:
                pass
        # final flush 确保最后一批不丢
        await self._flush_batch()
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception as e:
                log.warning("ws close error: %s", e)

    # ── 主循环 ──

    async def _main_loop(self) -> None:
        """断连时退避重连，连上后跑 consume + health"""
        while not self._stop.is_set():
            try:
                await self._connect()
                # 连上后同时跑消费 + 健康检查
                await asyncio.gather(
                    self._consume_loop(),
                    self._health_loop(),
                )
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("quote consumer loop error: %s, will reconnect", e)
            if not self._stop.is_set():
                await asyncio.sleep(self.RECONNECT_INITIAL)

    async def _connect(self) -> None:
        """指数退避重连（1s → 2s → ... → 30s）"""
        try:
            from websockets.client import connect
        except ImportError:
            log.exception("websockets library not installed (pip install websockets)")
            raise

        delay = self.RECONNECT_INITIAL
        while not self._stop.is_set():
            try:
                # ping_interval=15s 主动 ping, ping_timeout=60s 给足行情低谷容错
                self._ws = await connect(self.url, ping_interval=15, ping_timeout=60)
                log.info("quote_consumer connected: %s", self.url)
                return
            except Exception as e:
                log.warning("ws connect failed: %s, retry in %.1fs", e, delay)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=delay)
                except asyncio.TimeoutError:
                    pass
                delay = min(delay * 2, self.RECONNECT_MAX)

    async def _consume_loop(self) -> None:
        """async for msg in self._ws: parse + fan-out"""
        while not self._stop.is_set():
            try:
                raw = await self._ws.recv()
            except Exception as e:
                log.warning("ws recv error: %s", e)
                raise  # 让 _main_loop 走重连
            tick = self._parse_tick(raw)
            if tick is None:
                continue
            await self._fanout_tick(tick)

    async def _health_loop(self) -> None:
        """30s 心跳 + 60s 无 tick 警告"""
        while not self._stop.is_set():
            await asyncio.sleep(self.HEALTH_INTERVAL)
            if self._stop.is_set():
                return
            now = time.time()
            log.info(
                "[quote_consumer health] ticks_total=%d last_tick_age=%.1fs",
                self._tick_count,
                (now - self._last_tick_ts) if self._last_tick_ts else -1.0,
            )
            if self._last_tick_ts and (now - self._last_tick_ts) > self.NO_TICK_WARN:
                log.warning(
                    "[quote_consumer] no tick for %.1fs",
                    now - self._last_tick_ts,
                )

    # ── Tick 解析 + fan-out ──

    @staticmethod
    def _parse_tick(raw: str) -> Optional[dict]:
        """解析 hqserver JSON payload → {stock_code, last_price, snapshot{23 字段}, fields[], body}

        📌 hqserver 消息格式（hq/hqserver.py:159-169）：
           {"type":"quote","channel":"quote_update",
            "data":{"stock_code":"600519.SH","last_price":1820.5,"fields":[...],"body":"..."}}
        📌 fields 数组 31 字段索引（QMT publisher format_quote + hqserver 透传）：
           [0]  stock_code
           [1]  datetime (yyyyMMddHHmmss.sss)
           [2]  last_price
           [3]  open_price / [4] high_price / [5] low_price / [6] prev_close
           [7]  volume / [8] amount
           [9]  openInt (持仓量) / [10] transactionNum (成交笔数)
           [11..15] ask1_price..ask5_price (卖价递增)
           [16..20] bid1_price..bid5_price (买价递减)
           [21..25] ask1_vol..ask5_vol / [26..30] bid1_vol..bid5_vol
        📌 解析失败 / 非 quote_update 类型 → 返 None（静默忽略）
        """
        try:
            msg = json.loads(raw)
        except (ValueError, TypeError):
            return None
        if msg.get("channel") != "quote_update" or msg.get("type") != "quote":
            return None
        data = msg.get("data") or {}
        stock_code = data.get("stock_code")
        last_price = data.get("last_price")
        if not stock_code or last_price is None:
            return None

        # 取 fields（hqserver raw 31 字段）
        fields = data.get("fields") or []
        body = data.get("body") or ""

        # ──── 解 snapshot（23 数据列，缺字段给 0） ────
        def f(idx):
            try:
                return float(fields[idx]) if len(fields) > idx and fields[idx] else 0.0
            except (ValueError, TypeError):
                return 0.0

        def iv(idx):
            """volume / *_vol 取整数"""
            try:
                return int(float(fields[idx])) if len(fields) > idx and fields[idx] else 0
            except (ValueError, TypeError):
                return 0

        snapshot = {
            "stock_code": stock_code,
            "last_price": float(last_price),
            "open_price": f(3),
            "high_price": f(4),
            "low_price": f(5),
            "prev_close": f(6),
            "volume": iv(7),
            "amount": f(8),
            "ask1_price": f(11), "ask1_vol": iv(21),
            "ask2_price": f(12), "ask2_vol": iv(22),
            "ask3_price": f(13), "ask3_vol": iv(23),
            "ask4_price": f(14), "ask4_vol": iv(24),
            "ask5_price": f(15), "ask5_vol": iv(25),
            "bid1_price": f(16), "bid1_vol": iv(26),
            "bid2_price": f(17), "bid2_vol": iv(27),
            "bid3_price": f(18), "bid3_vol": iv(28),
            "bid4_price": f(19), "bid4_vol": iv(29),
            "bid5_price": f(20), "bid5_vol": iv(30),
        }

        return {
            "stock_code": stock_code,
            "last_price": float(last_price),
            "snapshot": snapshot,    # 23 字段 dict → quote_cache
            "fields": fields,        # 原 31 字段 → 前端 quote store 用
            "body": body,            # 原 GBK 字符串 → 前端 quote store 用
        }

    async def _fanout_tick(self, tick: dict) -> None:
        """写 cache + 入 batch buffer (不去重)

        - 不做股票级去重, 同股票多 tick 全部入 buffer
        - 50 条 OR 1 秒触发 flush (双阈值)
        - 仍走 broadcast_to_stock 按订阅过滤 (前端 ws payload 格式不变)
        """
        stock_code = tick.get("stock_code")
        snapshot = tick.get("snapshot") or {}
        self._latest_price[stock_code] = tick.get("last_price", 0.0)
        self._last_tick_ts = time.time()
        self._tick_count += 1

        # 写内存 cache (O(1) dict set + dirty mark)
        if snapshot and snapshot.get("stock_code"):
            quote_cache.set(snapshot)

        # 入 batch buffer (锁内: append + 阈值判定)
        should_flush = False
        async with self._batch_lock:
            self._batch_buf.append(tick)
            if len(self._batch_buf) >= self._batch_max:
                should_flush = True

        if should_flush:
            await self._flush_batch()

    async def _flush_batch(self) -> None:
        """取出 buffer 内全部 tick (按订阅过滤) 并广播。

        不去重: buffer 内 N 条 tick 可能同股票多次, 全部推到 ws (1 个 frame 装 N 个 tick dict)。
        """
        async with self._batch_lock:
            if not self._batch_buf:
                return
            ticks = list(self._batch_buf)
            self._batch_buf.clear()
            self._last_flush_ts = time.time()

        # 1 次 broadcast_batch: 每个 ws 客户端收到自己订阅的 tick batch
        try:
            delivered = await ws_manager.broadcast_batch(ticks=ticks)
        except Exception:
            log.exception("ws quote_batch broadcast failed (non-fatal)")
            delivered = 0

        log.debug("[quote_consumer batch] flushed %d ticks, delivered to %d subs",
                  len(ticks), delivered)

    async def _flusher_loop(self) -> None:
        """定时 flush 后台 task: 防止慢市累积超 1 秒

        每 self._batch_flush_ms/2 ms 检查一次 (100ms 间隔, 1s flush 上限误差 ±100ms)
        """
        interval = max(50, self._batch_flush_ms // 4) / 1000.0  # 100ms
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
                return  # stop 触发, 正常退出
            except asyncio.TimeoutError:
                pass  # 间隔到, 检查是否需要 flush
            # 检查距上次 flush 是否超过阈值
            now = time.time()
            elapsed_ms = (now - self._last_flush_ts) * 1000
            if elapsed_ms >= self._batch_flush_ms:
                await self._flush_batch()


# ─────────────── Module-level singleton（仿 RPClient 模式） ───────────────


_quote_consumer: Optional[QuoteConsumer] = None


async def get_quote_consumer() -> QuoteConsumer:
    """获取或创建 QuoteConsumer 单例（main.py startup 调用）"""
    global _quote_consumer
    if _quote_consumer is None:
        from server.config import settings
        qc = QuoteConsumer(url=settings.HQ_WS_URL)
        _quote_consumer = qc
        # 不 await start()，让它跑后台 task
        asyncio.ensure_future(qc.start())
    return _quote_consumer


async def close_quote_consumer() -> None:
    """停止 QuoteConsumer（main.py shutdown 调用）"""
    global _quote_consumer
    if _quote_consumer is not None:
        await _quote_consumer.stop()
        _quote_consumer = None


__all__ = ["QuoteConsumer", "get_quote_consumer", "close_quote_consumer"]
