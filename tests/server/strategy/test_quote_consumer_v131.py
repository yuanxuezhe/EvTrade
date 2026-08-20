"""
test_quote_consumer_v131.py — quote_consumer v131 quote-batch-flush 单测

覆盖:
- 股票去重: 同窗口内同 stock_code 多 tick → 只推最新 (batch 内 1 个 stock_code 1 tick)
- size 阈值: 累积 50 tick 立即 flush (不是等 1 秒)
- time 阈值: 不足 50 tick 但 ≥ 1 秒也必须 flush
- 订阅过滤: broadcast_batch 只发 tick 给订阅它的 ws
- zero 订阅: 没 ws 客户端订阅时 broadcast_batch 不发
- final flush: stop() 时最后一批不丢

设计: 直接 new QuoteConsumer, 不启动 _main_loop + ws 连接, 只测
_fanout_tick / _flush_batch / _flusher_loop 三个方法 + ws_manager mock。
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from typing import Any, Dict, List

import pytest

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.insert(0, _PROJECT_ROOT)
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "server"))

from server.services.strategy.quote_consumer import QuoteConsumer  # noqa: E402


# ──────────────── Fake ws_manager ────────────────


class FakeWsManager:
    """mock ws_manager.broadcast_batch 捕获所有 payload。"""

    def __init__(self):
        self.calls: List[Dict[str, Any]] = []

    async def broadcast_batch(self, ticks, channel="quote_update", trace_id=None):
        # 捕获 stock_code 列表而非整个 tick (避免 snapshot 比较复杂)
        self.calls.append({
            "ts": time.monotonic(),
            "tick_count": len(ticks),
            "stock_codes": sorted([t["stock_code"] for t in ticks]),
            "last_prices": {t["stock_code"]: t["last_price"] for t in ticks},
        })
        return 1  # 假装 1 个 ws 客户端订阅成功


# ──────────────── Helpers ────────────────


def _make_consumer(batch_max=50, flush_ms=1000):
    """绕过 __init__ 的 url/ws/_main_loop, 直接造 QuoteConsumer 测 batch 字段。"""
    c = QuoteConsumer.__new__(QuoteConsumer)
    c.url = "ws://test"
    c._latest_price = {}
    c._stop = asyncio.Event()
    c._ws = None
    c._last_tick_ts = None
    c._tick_count = 0
    c._batch_max = batch_max
    c._batch_flush_ms = flush_ms
    c._batch_buf = []  # v131.1 list (no dedup)
    c._batch_lock = asyncio.Lock()
    c._last_flush_ts = time.monotonic()
    c._flusher_task = None
    return c


def _make_tick(code: str, last_price: float) -> Dict[str, Any]:
    return {
        "stock_code": code,
        "last_price": last_price,
        "snapshot": {"stock_code": code, "last_price": last_price},
        "fields": [code, "093000", str(last_price)] + ["0"] * 28,
        "body": "",
    }


@pytest.fixture
def fake_wsm():
    """注入 fake ws_manager 并返回 fake 对象供断言。"""
    fake = FakeWsManager()
    import server.services.strategy.quote_consumer as qc_mod
    qc_mod.ws_manager = fake
    yield fake
    # 还原
    import server.ws.manager as wm_mod
    qc_mod.ws_manager = wm_mod.ws_manager


# ──────────────── 1. 不做股票级去重 (v131.1) ────────────────


class TestNoDeduplication:
    """v131.1: 同窗口内同 stock_code 多 tick 全部保留, 用户要求看到每一根 tick。"""

    @pytest.mark.asyncio
    async def test_same_stock_multiple_ticks_all_kept(self, fake_wsm):
        c = _make_consumer(batch_max=50, flush_ms=10000)  # 长 flush 防止 timer 抢
        # 同股票 5 次 tick, 价递增 - 全部保留
        for i in range(5):
            await c._fanout_tick(_make_tick("600519.SH", last_price=100.0 + i))

        await c._flush_batch()

        assert len(fake_wsm.calls) == 1
        # 5 条全部保留 (no dedup)
        assert fake_wsm.calls[0]["tick_count"] == 5
        # 验证 stock_code 出现 5 次 (last_prices dict 同名 key 覆盖, 但 tick_count=5)
        assert fake_wsm.calls[0]["stock_codes"].count("600519.SH") == 5
        # 价递增 100/101/102/103/104 - last_prices 仅保留 dict 里最后一次
        assert fake_wsm.calls[0]["last_prices"]["600519.SH"] == 104.0

    @pytest.mark.asyncio
    async def test_different_stocks_all_kept(self, fake_wsm):
        c = _make_consumer(batch_max=50, flush_ms=10000)
        for code in ["600519.SH", "600000.SH", "000001.SZ", "688981.SH"]:
            await c._fanout_tick(_make_tick(code, last_price=1.0))

        await c._flush_batch()

        assert len(fake_wsm.calls) == 1
        assert fake_wsm.calls[0]["tick_count"] == 4
        assert sorted(fake_wsm.calls[0]["stock_codes"]) == sorted(
            ["600519.SH", "600000.SH", "000001.SZ", "688981.SH"]
        )

    @pytest.mark.asyncio
    async def test_interleaved_same_stock_all_kept(self, fake_wsm):
        """同股票穿插入 buffer 仍全部保留 - 用户场景: 5 只 ETF 交替 tick"""
        c = _make_consumer(batch_max=50, flush_ms=10000)
        # 5 ETF 各 tick 3 次, 交替入队 = 15 条
        codes = ["512760.SH", "515650.SH", "515880.SH", "560470.SH", "588710.SH"]
        for round_n in range(3):
            for code in codes:
                await c._fanout_tick(_make_tick(code, last_price=round_n + 1))

        await c._flush_batch()
        assert fake_wsm.calls[0]["tick_count"] == 15
        # 每只股票出现 3 次
        for code in codes:
            assert fake_wsm.calls[0]["stock_codes"].count(code) == 3


# ──────────────── 2. size 阈值 (50 tick 立即 flush) ────────────────


class TestSizeThreshold:
    """累积 50 条 tick → 立即 flush (不等 1s)。"""

    @pytest.mark.asyncio
    async def test_50_ticks_immediate_flush(self, fake_wsm):
        c = _make_consumer(batch_max=50, flush_ms=10000)  # 长 flush 防干扰
        for i in range(50):
            await c._fanout_tick(_make_tick(f"{(i % 100):06d}.SH", last_price=1.0))

        # 第 50 条入队时 size 阈值触发, _fanout_tick 内部 await _flush_batch
        # 所以 50 条入完调用一次 broadcast_batch
        assert len(fake_wsm.calls) == 1
        assert fake_wsm.calls[0]["tick_count"] == 50

    @pytest.mark.asyncio
    async def test_51_ticks_two_flushes(self, fake_wsm):
        c = _make_consumer(batch_max=50, flush_ms=10000)
        for i in range(51):
            await c._fanout_tick(_make_tick(f"{(i % 100):06d}.SH", last_price=1.0))

        # 50 条时触发 flush, _batch_buf 清空; 第 51 条再入队, 不到阈值, 不会自动 flush
        assert len(fake_wsm.calls) == 1
        assert fake_wsm.calls[0]["tick_count"] == 50
        assert len(c._batch_buf) == 1  # 第 51 条还在 buffer

        # 手动 flush 验证第 51 条
        await c._flush_batch()
        assert len(fake_wsm.calls) == 2
        assert fake_wsm.calls[1]["tick_count"] == 1


# ──────────────── 3. time 阈值 (1s 兜底) ────────────────


class TestTimeThreshold:
    """不足 size 阈值, 但距 last_flush_ts ≥ 1s → flush。"""

    @pytest.mark.asyncio
    async def test_timer_triggers_after_flush_ms(self, fake_wsm):
        # flush_ms=200 让测试快
        c = _make_consumer(batch_max=50, flush_ms=200)
        # 启动 flusher 后台 task
        c._flusher_task = asyncio.ensure_future(c._flusher_loop())
        try:
            # 入 1 条 tick
            await c._fanout_tick(_make_tick("600519.SH", 1.0))
            assert len(fake_wsm.calls) == 0  # size 未到, 还没 flush

            # 等 250ms (略大于 200ms flush_ms)
            await asyncio.sleep(0.25)

            # timer 应已 flush
            assert len(fake_wsm.calls) == 1
            assert fake_wsm.calls[0]["tick_count"] == 1
        finally:
            c._stop.set()
            await asyncio.sleep(0.05)
            if not c._flusher_task.done():
                c._flusher_task.cancel()

    @pytest.mark.asyncio
    async def test_size_threshold_resets_timer(self, fake_wsm):
        """size 阈值触发后 _last_flush_ts 重置, timer 重新计时。"""
        c = _make_consumer(batch_max=10, flush_ms=200)
        c._flusher_task = asyncio.ensure_future(c._flusher_loop())
        try:
            # 入 10 条触发 size flush
            for i in range(10):
                await c._fanout_tick(_make_tick(f"{(i % 100):06d}.SH", 1.0))
            assert len(fake_wsm.calls) == 1
            assert fake_wsm.calls[0]["tick_count"] == 10

            # 再入 5 条 (size 不到 10)
            for i in range(5):
                await c._fanout_tick(_make_tick(f"{(i % 100):06d}.SH", 1.0))
            assert len(fake_wsm.calls) == 1  # 还是 1 次 flush

            # 等 250ms (timer 触发)
            await asyncio.sleep(0.25)
            assert len(fake_wsm.calls) == 2
            assert fake_wsm.calls[1]["tick_count"] == 5  # 后入的 5 条
        finally:
            c._stop.set()
            await asyncio.sleep(0.05)
            if not c._flusher_task.done():
                c._flusher_task.cancel()


# ──────────────── 4. 订阅过滤 (ws_manager.broadcast_batch 已实现) ────────────────


class TestSubscriptionFiltering:
    """broadcast_batch 收到 N tick, 按 ws 订阅过滤后发对应 tick。

    注: 本测试不直接验 broadcast_batch (那是 ws_manager 单测的事),
    这里验 quote_consumer 调 broadcast_batch 时传入的 ticks 列表正确,
    (订阅过滤本身在 ws_manager.broadcast_batch 内完成)。
    """

    @pytest.mark.asyncio
    async def test_flush_passes_all_ticks_no_dedup(self, fake_wsm):
        c = _make_consumer(batch_max=50, flush_ms=10000)
        # 5 只不同股票 + 2 只同股票 (no dedup = 7 条全保留)
        codes_prices = [
            ("600519.SH", 1.0), ("000001.SZ", 2.0), ("688981.SH", 3.0),
            ("600519.SH", 1.5),  # 同股票第 2 次 (不 dedup)
            ("512760.SH", 4.0), ("515650.SH", 5.0), ("000001.SZ", 2.5),  # 同股票第 2 次
        ]
        for code, p in codes_prices:
            await c._fanout_tick(_make_tick(code, p))

        await c._flush_batch()

        assert len(fake_wsm.calls) == 1
        # 7 条全部保留 (no dedup), tick_count 反映真实条数
        assert fake_wsm.calls[0]["tick_count"] == 7
        last_prices = fake_wsm.calls[0]["last_prices"]
        # last_prices dict 仅保留同名 key 的最后一次 (dict 特性, 不是 dedup)
        # 真实前端拿到的 ticks[] 才是 7 条
        assert last_prices["600519.SH"] == 1.5
        assert last_prices["000001.SZ"] == 2.5


# ──────────────── 5. zero 订阅 (broadcast_batch 不发) ────────────────


class TestZeroSubscribers:
    """无 ws 客户端订阅时 broadcast_batch 返回 0, quote_consumer 不报错。"""

    @pytest.mark.asyncio
    async def test_zero_subs_no_error(self):
        fake = FakeWsManager()
        # mock broadcast_batch 模拟零订阅
        async def fake_zero(ticks, channel="quote_update", trace_id=None):
            fake.calls.append({"tick_count": len(ticks)})
            return 0
        fake.broadcast_batch = fake_zero

        import server.services.strategy.quote_consumer as qc_mod
        qc_mod.ws_manager = fake
        try:
            c = _make_consumer(batch_max=50, flush_ms=10000)
            for i in range(5):
                await c._fanout_tick(_make_tick(f"{(i % 100):06d}.SH", 1.0))

            # 手动 flush, 应该不报错
            await c._flush_batch()
            assert len(fake.calls) == 1
            assert fake.calls[0]["tick_count"] == 5
        finally:
            import server.ws.manager as wm_mod
            qc_mod.ws_manager = wm_mod.ws_manager


# ──────────────── 6. final flush (stop 时最后一批不丢) ────────────────


class TestFinalFlush:
    """stop() 时调 _flush_batch, 最后未满批的 tick 必须 flush 出去。"""

    @pytest.mark.asyncio
    async def test_stop_flushes_remaining_buffer(self, fake_wsm):
        c = _make_consumer(batch_max=50, flush_ms=10000)
        # 入 5 条 (size 未到 50, 不会自动 flush)
        for i in range(5):
            await c._fanout_tick(_make_tick(f"{(i % 100):06d}.SH", 1.0))

        # 此时 broadcast_batch 还未被调 (size 未达)
        assert len(fake_wsm.calls) == 0
        assert len(c._batch_buf) == 5

        # 直接调 _flush_batch 模拟 stop 流程 (stop 需要 _ws, 这里绕过)
        await c._flush_batch()
        assert len(fake_wsm.calls) == 1
        assert fake_wsm.calls[0]["tick_count"] == 5
        assert len(c._batch_buf) == 0


# ──────────────── 7. 并发安全 ────────────────


class TestConcurrency:
    """多协程并发 _fanout_tick 不丢数据, _batch_buf 锁正确。"""

    @pytest.mark.asyncio
    async def test_concurrent_fanout_no_loss(self, fake_wsm):
        c = _make_consumer(batch_max=1000, flush_ms=10000)  # 永不到 size, 也不会 timer flush

        # 10 协程各入 50 tick (50 unique stocks × 10 same) - v131.1 不去重, 应保留 500 条
        async def worker(worker_id):
            for i in range(50):
                await c._fanout_tick(_make_tick(f"{(i % 50):06d}.SH", 1.0))

        await asyncio.gather(*[worker(i) for i in range(10)])
        # 不 dedup: 500 条全在 buffer
        assert len(c._batch_buf) == 500

        await c._flush_batch()
        assert len(fake_wsm.calls) == 1
        assert fake_wsm.calls[0]["tick_count"] == 500