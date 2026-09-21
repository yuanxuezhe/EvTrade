"""
server/services/quote_sync/manager.py — per-stock 并发守护

启动自动增量同步 (run_startup_backfill) 与前端手动单日同步 (API /sync) 共用
sync_one_day 核心。为避免同一只证券被两个入口同时拉同一天 (重复压 broker),
这里提供 per-stock asyncio.Lock 守护:

  - sync_one_day_guarded(stock, day): 拿该证券锁再调 sync_one_day
  - run_startup_backfill_guarded(): 拿锁跑启动自动补全 (逐日)

同一只证券内串行; 不同证券互不阻塞 (各持各的锁)。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Dict

from server.services.quote_sync import sync as sync_mod

log = logging.getLogger("quote_sync.manager")


class QuoteSyncManager:
    def __init__(self) -> None:
        self._locks: Dict[str, asyncio.Lock] = {}
        self._meta_lock = asyncio.Lock()
        self._startup_task: asyncio.Task | None = None

    def _lock_for(self, stock: str) -> asyncio.Lock:
        # 缓存 per-stock lock (event loop 内访问, 单线程安全)
        lk = self._locks.get(stock)
        if lk is None:
            lk = asyncio.Lock()
            self._locks[stock] = lk
        return lk

    async def sync_one_day_guarded(self, stock: str, day: str):
        """per-stock 锁守护的单日同步 (手动入口)。"""
        lk = self._lock_for(stock)
        async with lk:
            return await sync_mod.sync_one_day(stock, day)

    async def start_startup_backfill(self) -> None:
        """启动钩子调: 后台跑启动自动增量补全 (不阻塞启动)。"""
        if self._startup_task is not None and not self._startup_task.done():
            return
        self._startup_task = asyncio.ensure_future(self._run_startup_guarded())
        log.info("[quote_sync] 启动自动补全任务已派发")

    async def _run_startup_guarded(self) -> None:
        """逐日补平, 单只内逐日且持 per-stock 锁。change 2026-09-04: 改 chunk 拉取。

        按 sysconfig `quote_sync_chunk_days` 把 [next_day, cap] 拆成 N 天/批,
        串行调 sync_one_day (同 sync_chunk 内部行为; 这里自己循环保持 per-stock
        锁外层可见, 可中断可恢复).
        """
        from server.services.quote_sync.sync import _cap_day, _next_day
        from server.services.quote_sync import repository as repo
        from server.services.sysconfig import get

        pending = await asyncio.to_thread(sync_mod.read_auto_pending)
        if not pending:
            log.info("[quote_sync] 启动自动补全: 无 pending 证券")
            return
        chunk_days = int(get("quote_sync_chunk_days", default=10))
        if not (1 <= chunk_days <= 30):
            chunk_days = 10
        log.info("[quote_sync] 启动自动补全: %d 只 (chunk_days=%d) %s",
                 len(pending), chunk_days, ", ".join(pending))

        for stock in pending:
            lk = self._lock_for(stock)
            async with lk:
                cfg = await asyncio.to_thread(repo.get_config, stock)
                if cfg is None:
                    continue
                cap = _cap_day(cfg.end_date or "")
                day = _next_day(cfg.last_loaded_date or cfg.start_date)
                try:
                    # change 2026-09-04: 按 chunk_days 分批拉, 一天失败则整批跳到下一批
                    from datetime import datetime, timedelta
                    cur = datetime.strptime(day, "%Y%m%d").date()
                    ed = datetime.strptime(cap, "%Y%m%d").date()
                    while cur <= ed:
                        chunk_end = min(cur + timedelta(days=chunk_days - 1), ed)
                        d = cur
                        while d <= chunk_end:
                            ds = d.strftime("%Y%m%d")
                            try:
                                await sync_mod.sync_one_day(stock, ds)
                            except sync_mod.BrokerError as e:
                                log.warning("[quote_sync] %s %s 启动补全失败: %s (跳过本批, 下次启动续)",
                                            stock, ds, e)
                                d = chunk_end + timedelta(days=1)
                                break
                            d += timedelta(days=1)
                        cur = d
                    log.info("[quote_sync] %s 已追平到 %s", stock, cap)
                except Exception as e:
                    log.warning("[quote_sync] %s 启动补全在 %s 中断: %s (下次启动续)",
                                stock, day, e)
                    continue

    async def shutdown(self) -> None:
        """关闭: 取消未完成的启动补全任务。"""
        if self._startup_task is not None and not self._startup_task.done():
            self._startup_task.cancel()
            try:
                await self._startup_task
            except (asyncio.CancelledError, Exception):
                pass


# 单例
manager = QuoteSyncManager()
