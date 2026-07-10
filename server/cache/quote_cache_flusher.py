"""
server/cache/quote_cache_flusher.py — 周期性把内存 cache 同步到 MySQL（2026-07-10 quote-cache）

📌 设计目标：
   tick 流走 cache.set()（O(1)），不再每条 await MySQL UPSERT（实测 200ms/次）。
   本模块作为后台 task，定时把 cache 中"自上次 flush 后有更新"的 snapshot
   批量 UPSERT 到 MySQL，平衡"实时性"和"持久化开销"。

📌 触发条件（任一）：
   1. 定时器：每 QUOTE_CACHE_FLUSH_INTERVAL 秒（默认 60s）
   2. 阈值：cache 中 dirty 数量 > QUOTE_CACHE_FLUSH_DIRTY_THRESHOLD（默认 100）

📌 失败处理：
   - 单条 UPSERT 失败 → log 警告，不影响其他条
   - 整批失败 → restore_dirty 回滚 dirty 标记，下个周期重试
"""
from __future__ import annotations

import asyncio
import logging
import time

from sqlalchemy.exc import SQLAlchemyError

from server.cache.quote_cache import get_quote_cache
from server.config import settings
from server.db import db_session
from server.repo import quote_snapshots as quote_repo

log = logging.getLogger(__name__)


async def _flush_once() -> None:
    """执行一次 flush：从 cache 取 dirty 快照，批量写 MySQL。"""
    cache = get_quote_cache()
    snapshots, codes = cache.pop_dirty()
    if not snapshots:
        return  # 没有 dirty，零开销

    start = time.time()
    count = len(snapshots)
    failed_codes: set = set()

    try:
        # 每条单独 UPSERT（避雷：quote_repo.upsert 没有 batch 入口）
        # 用 to_thread 放到线程池，避免阻塞事件循环
        def _do_upsert_all():
            with db_session() as db:
                for code, snap in snapshots.items():
                    try:
                        quote_repo.upsert(db, code, snap)
                    except SQLAlchemyError as e:
                        failed_codes.add(code)
                        log.warning("flush upsert failed for %s: %s", code, e)

        await asyncio.to_thread(_do_upsert_all)
    except Exception as e:
        # 整批失败（例如 DB 完全不可用）→ 全部回滚 dirty
        log.exception("flush batch failed: %s; restoring %d dirty codes", e, len(codes))
        cache.restore_dirty(codes)
        return

    duration_ms = (time.time() - start) * 1000.0
    cache.record_flush(count, duration_ms)

    # 部分失败：回滚失败条的 dirty 标记（让下次重试）
    if failed_codes:
        remaining = codes - failed_codes
        if remaining:
            cache.restore_dirty(remaining)
        log.warning(
            "flush partial: %d ok, %d failed, %.1f ms",
            count - len(failed_codes), len(failed_codes), duration_ms,
        )
    else:
        log.info(
            "flush ok: %d snapshots, %.1f ms, cache_size=%d",
            count, duration_ms, cache.size(),
        )


async def _periodic_flush_loop() -> None:
    """主循环：定时 + 阈值双重触发 flush。"""
    cache = get_quote_cache()
    interval = settings.QUOTE_CACHE_FLUSH_INTERVAL
    threshold = settings.QUOTE_CACHE_FLUSH_DIRTY_THRESHOLD
    log.info(
        "quote_cache_flusher started: interval=%ds, dirty_threshold=%d",
        interval, threshold,
    )

    while True:
        try:
            # 阈值触发：dirty 太多 → 立即 flush
            if cache.stats()["dirty_count"] >= threshold:
                await _flush_once()
        except Exception:
            log.exception("periodic flush (threshold) failed")

        try:
            await asyncio.sleep(interval)
            # 定时触发
            await _flush_once()
        except asyncio.CancelledError:
            log.info("quote_cache_flusher cancelled, doing final flush")
            try:
                await _flush_once()
            except Exception:
                log.exception("final flush on shutdown failed")
            raise
        except Exception:
            log.exception("periodic flush (timer) failed")
            # 继续下一轮，不退出循环


def start_quote_cache_flusher() -> asyncio.Task:
    """启动后台 flush 协程（在 main.py 的 startup 钩子里调用）。

    返回 asyncio.Task 句柄，shutdown 时 cancel 它。
    """
    return asyncio.create_task(_periodic_flush_loop(), name="quote_cache_flusher")