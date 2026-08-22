"""
server/cache/quote_cache.py — 行情内存缓存

📌 设计动机：
   quote_consumer 之前每条 tick 都要 await MySQL UPSERT（实测 p50=200ms, p95=410ms），
   backend 实际处理速率被锁死在 ~6 ticks/s，而 hqserver 实际推送 ~4000+ ticks/s，
   99.85% 的 tick 积压。前端 ws 推送也因此延迟。

📌 解决方案：
   1. tick 进入 backend → 立即写内存 cache（O(1) dict set, ~微秒级）
   2. API 读行情 → 优先读 cache，miss 时查 DB 回填到 cache
   3. 后台 periodic flush task → 每 60s（可配）批量把 dirty 的 cache 同步到 MySQL

📌 一致性权衡：
   - 进程崩溃 → 最多丢失 QUOTE_CACHE_FLUSH_INTERVAL 秒数据（默认 60s）
   - cache 是 single source of truth for read，DB 是持久化备份
   - dirty tracking 用 set（_dirty_codes），避免全表扫描
"""
from __future__ import annotations

import asyncio
import logging
import time
from threading import Lock
from typing import Dict, Iterable, Optional, Set, Tuple

log = logging.getLogger(__name__)


class QuoteCache:
    """进程内行情快照缓存（latest-only, 每 stock_code 1 条）。

    📌 线程安全：
       - set/get 是简单 dict 操作，Python GIL 保护原子性
       - dirty tracking 的 pop_all 用 threading.Lock 保护
       - cache 读取路径完全无锁（热路径性能最大化）

    📌 数据结构：
       - _snapshots: Dict[str, dict]         主数据
       - _dirty: Set[str]                    自上次 flush 后有更新的 code
       - _stats: dict                        命中率统计
    """

    def __init__(self) -> None:
        self._snapshots: Dict[str, dict] = {}
        self._dirty: Set[str] = set()
        self._dirty_lock = Lock()
        # 统计：hit/miss/set/del 共四个计数器
        self._stats = {
            "hits": 0,
            "misses": 0,
            "sets": 0,
            "flushes": 0,
            "last_flush_ts": 0.0,
            "last_flush_count": 0,
            "last_flush_duration_ms": 0.0,
        }

    # ────────────────────── write path (热路径, 无锁) ──────────────────────

    def set(self, snapshot: dict) -> None:
        """写入或覆盖一条 snapshot。tick 热路径，O(1)。

        snapshot 字段：stock_code + 23 数据字段（与 repo/quote_snapshots 一致）
        """
        code = snapshot.get("stock_code")
        if not code:
            return
        self._snapshots[code] = snapshot
        # dirty 标记用 lock（set 操作非原子）
        with self._dirty_lock:
            self._dirty.add(code)
        self._stats["sets"] += 1

    # ────────────────────── read path (热路径, 无锁) ──────────────────────

    def get(self, stock_code: str) -> Optional[dict]:
        """读单条 snapshot。无锁 dict get，~100ns。"""
        snap = self._snapshots.get(stock_code)
        if snap is not None:
            self._stats["hits"] += 1
        else:
            self._stats["misses"] += 1
        return snap

    def multi_get(self, stock_codes: Iterable[str]) -> Dict[str, dict]:
        """批量读。返回 dict{stock_code: snapshot}, 不在 cache 的 code 不在结果里。

        调用方根据返回值判断哪些 code 走 DB 回填。
        """
        result = {}
        for code in stock_codes:
            if not code:
                continue
            snap = self._snapshots.get(code)
            if snap is not None:
                result[code] = snap
                self._stats["hits"] += 1
            else:
                self._stats["misses"] += 1
        return result

    def has(self, stock_code: str) -> bool:
        return stock_code in self._snapshots

    def size(self) -> int:
        """当前 cache 中 snapshot 数（不同 stock_code 数）"""
        return len(self._snapshots)

    # ────────────────────── flush path (后台 task, 锁) ──────────────────────

    def pop_dirty(self) -> Tuple[Dict[str, dict], Set[str]]:
        """取出所有 dirty 的 snapshot（原子操作），调用方负责写 DB。

        返回 (snapshots_to_flush, codes_to_clear_from_dirty)
        """
        with self._dirty_lock:
            if not self._dirty:
                return {}, set()
            codes = self._dirty.copy()
            snapshots = {code: self._snapshots[code] for code in codes if code in self._snapshots}
            self._dirty.clear()
        return snapshots, codes

    def restore_dirty(self, codes: Set[str]) -> None:
        """flush 失败时回滚 dirty 标记（下次重试）。"""
        if not codes:
            return
        with self._dirty_lock:
            self._dirty.update(codes)

    def record_flush(self, count: int, duration_ms: float) -> None:
        """记录一次 flush 的统计。"""
        self._stats["flushes"] += 1
        self._stats["last_flush_ts"] = time.time()
        self._stats["last_flush_count"] = count
        self._stats["last_flush_duration_ms"] = duration_ms

    # ────────────────────── stats / debug ──────────────────────

    def stats(self) -> dict:
        """健康度统计（供 /health/quote-cache 之类接口或日志）。"""
        total_reads = self._stats["hits"] + self._stats["misses"]
        hit_rate = self._stats["hits"] / total_reads if total_reads > 0 else 0.0
        return {
            **self._stats,
            "size": self.size(),
            "dirty_count": len(self._dirty),
            "hit_rate": round(hit_rate, 4),
            "total_reads": total_reads,
        }


# ────────────────────── module-level singleton ──────────────────────

_cache: Optional[QuoteCache] = None


def get_quote_cache() -> QuoteCache:
    """获取进程级单例 QuoteCache（懒加载）。"""
    global _cache
    if _cache is None:
        _cache = QuoteCache()
        log.info("QuoteCache singleton initialized")
    return _cache


def reset_quote_cache_for_tests() -> None:
    """测试用：重置 singleton（生产代码不调用）。"""
    global _cache
    _cache = None