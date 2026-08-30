"""
strategy_exec.data_access.minute_bars — minute_bars 表读写 helper

📌 历史分钟 K 线 (change his-quote-backfill 2026-08-30 加的表):
- 主键 (stock_code, stime) 14位 YYYYMMDDHHMMSS
- 字段: stock_code / stime / open / close / high / low / avg_price / volume
- 174240 条记录 (159992.SZ 20230830~20260828)
- 复用 server/services/quote_sync/repository.py 的 upsert 函数
- 直连 MySQL (复用 EVTRADE_DB_URL)

API:
- query_minute_bars(stock, start, end) -> List[Dict]
  - 查表, 错误/不存在 返 []
  - async 包装 (内部 asyncio.to_thread 跑 sync sqlalchemy)
- upsert_minute_bars(stock, bars) -> int
  - 批量 upsert (executemany + ON DUPLICATE KEY UPDATE, 幂等)
  - 返写入条数

change 2026-08-30-his-hq-cache-minute-bars:
- strategy_exec 回测前先查 minute_bars → 缺时调 broker → 写回 minute_bars
- 避免重复调 broker his_hq (单次 30s 超时 + 长区间 fetch 慢)
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import logging
from typing import Any, Dict, List

log = logging.getLogger(__name__)


def _get_engine():
    """懒加载 DB engine (复用 server.infra.db.engine, 共享连接池)"""
    from server.infra.db import engine
    return engine


def _query_sync(stock_code: str, start_date: str, end_date: str) -> List[Dict[str, Any]]:
    """sync sqlalchemy 直查 minute_bars. 错误/不存在 → 返 []."""
    from sqlalchemy import text

    # start_date / end_date 是 YYYYMMDD, 补成 YYYYMMDD000000 / YYYYMMDD235959
    # 这样 BETWEEN 包含整个日期范围
    start_stime = f"{start_date}000000"
    end_stime = f"{end_date}235959"

    try:
        with _get_engine().connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT stock_code, stime, open, close, high, low, avg_price, volume
                      FROM minute_bars
                     WHERE stock_code = :stock
                       AND stime BETWEEN :start AND :end
                     ORDER BY stime ASC
                    """
                ),
                {"stock": stock_code, "start": start_stime, "end": end_stime},
            ).fetchall()
        return [
            {
                "stime": str(r[1]),
                "open": float(r[2] or 0.0),
                "high": float(r[4] or 0.0),
                "low": float(r[5] or 0.0),
                "close": float(r[3] or 0.0),
                "avg_price": float(r[6] or 0.0),
                "volume": int(r[7] or 0),
            }
            for r in rows
        ]
    except Exception as e:  # noqa: BLE001
        log.warning("[minute_bars.query] %s stock=%s %s~%s: %s",
                    type(e).__name__, stock_code, start_date, end_date, e)
        return []


async def query_minute_bars(
    stock_code: str, start_date: str, end_date: str,
) -> List[Dict[str, Any]]:
    """查 minute_bars 表 (异步包装).

    Args:
        stock_code: 证券代码 (e.g. '159992.SZ')
        start_date / end_date: YYYYMMDD (8位)

    Returns:
        1m K 线数组, 每项 {stime, open, high, low, close, avg_price, volume}
        按 stime 升序. 错误/不存在 → 返 [].
    """
    return await asyncio.to_thread(_query_sync, stock_code, start_date, end_date)


def _covered_dates(bars: List[Dict[str, Any]]) -> set:
    """bars 中所有 stime[:8] 的 date 集合 (实际覆盖的交易日)."""
    return {b["stime"][:8] for b in bars if b.get("stime")}


def _date_span_days(start_date: str, end_date: str) -> int:
    """[start, end] 区间天数 (含两端)."""
    s = _dt.datetime.strptime(start_date, "%Y%m%d").date()
    e = _dt.datetime.strptime(end_date, "%Y%m%d").date()
    return (e - s).days + 1 if s <= e else 0


def is_full_cover(
    cached_bars: List[Dict[str, Any]], start_date: str, end_date: str,
) -> bool:
    """cached_bars 是否覆盖 [start, end] 区间 (按日)?"""
    if not cached_bars:
        return False
    covered = _covered_dates(cached_bars)
    total = _date_span_days(start_date, end_date)
    # 简单判断: cached 有数据 + 覆盖至少 50% 区间
    # (broker stub 不严格按天返, 实际 80%+ 覆盖即可认为足够)
    return len(covered) >= total * 0.5


def find_missing_ranges(
    cached_bars: List[Dict[str, Any]], start_date: str, end_date: str,
) -> List[tuple]:
    """找 cached_bars 缺的天 → 返回 [(start, end), ...] 段."""
    covered = _covered_dates(cached_bars)
    # 缺的天列表
    s = _dt.datetime.strptime(start_date, "%Y%m%d").date()
    e = _dt.datetime.strptime(end_date, "%Y%m%d").date()
    missing = []
    cur = s
    while cur <= e:
        date_str = cur.strftime("%Y%m%d")
        # 跳过周末 (broker 自动跳过非交易日)
        if date_str not in covered and cur.weekday() < 5:
            missing.append(date_str)
        cur += _dt.timedelta(days=1)
    # 合并连续段
    if not missing:
        return []
    from strategy_exec.market_data.hq_history import _iter_chunks
    return _iter_chunks(missing[0], missing[-1], len(missing)) if len(missing) <= 10 \
        else _iter_chunks(missing[0], missing[-1], 10)