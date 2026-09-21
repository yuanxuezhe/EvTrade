"""
server/services/quote_sync/sync.py — 按日补全核心 + 启动自动增量同步

`sync_one_day(stock, day)`:
  拉 broker 当日 1m → to_record (VWAP) → upsert minute_bars → 推进游标。
  成功 (含假日 0 根) 返 dict, 失败 raise BrokerError (游标不动)。

启动自动增量同步 (REQ-QSB-006):
  read_all_auto_pending() 列出 auto_sync=1 且 last_loaded_date<昨天 的证券;
  run_startup_backfill() 后台逐日补平 (per-stock 串行, 不并发多标的)。
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List

from server.config import settings
from server.tables import QuoteSyncConfig
from server.services.quote_sync import repository as repo
from server.services.quote_sync.broker import (
    BrokerError, get_his_hq_client, to_record,
)

log = logging.getLogger("quote_sync.sync")


def _yesterday() -> str:
    return (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")


def _next_day(day: str) -> str:
    d = datetime.strptime(day, "%Y%m%d") + timedelta(days=1)
    return d.strftime("%Y%m%d")


def _cap_day(end_date: str) -> str:
    """补全末天 = min(end_date 或 昨天, 昨天)。end_date 空=开放到昨天。"""
    y = _yesterday()
    if not end_date:
        return y
    return min(end_date, y)


async def sync_one_day(stock_code: str, day: str) -> Dict[str, Any]:
    """同步单只证券某一天 + 写操作记录到 quote_sync_config。

    - 成功 (含假日 0 根): upsert minute_bars → **重算** last_loaded_date
      (= minute_bars 该证券实际最大 stime 日期) → status=success, 清 error_msg。
    - 失败 (broker 连不上/异常): status=failed + error_msg, last_loaded_date 不动,
      然后 re-raise BrokerError (API 返 code:1 + 原因; 前端停止循环显示原因)。

    Returns (成功时): {ok:bool, day:str, bars:int, last_loaded_date:str}
    """
    cfg = repo.get_config(stock_code)
    if cfg is None:
        await asyncio.to_thread(repo.record_failure, stock_code,
                                f"NO_CONFIG: {stock_code} 无配置行")
        raise BrokerError(f"NO_CONFIG: {stock_code} 无 quote_sync_config 配置行")

    # 不提前按周末/假日跳过 — 走 broker his_hq 拉取 (空日 / 节假日由 broker
    # 返 END_OF_HIS_HQ 标记或 idle 超时空返 [], 视为成功空, 游标照常推进)。
    # 这样 `last_loaded_date` 跟实际有数据的天一致 (即使中间隔了周末/假日)。
    client = get_his_hq_client()
    try:
        await client.connect()
        # change 2026-09-03 unify-his-hq-broker-client: 统一调 HisHqClient.fetch_bars
        # (代替旧 HisHqClient.fetch_one_day, 跨 server/scripts/strategy_exec 一致)
        rows = await client.fetch_bars(stock_code, day, day)
        records = [to_record(stock_code, r) for r in rows]
        # 同步 IO 放线程 (broker 拉取已 await, 落库是同步 SQLAlchemy)
        n = await asyncio.to_thread(repo.upsert_minute_bars, records)
    except BrokerError as e:
        await asyncio.to_thread(repo.record_failure, stock_code, str(e))
        raise
    except Exception as e:
        log.exception("[quote_sync] sync_one_day %s %s 未预期异常", stock_code, day)
        await asyncio.to_thread(repo.record_failure, stock_code, f"SYNC_ERROR: {e}")
        raise BrokerError(f"SYNC_ERROR: {e}") from e

    # 成功: 重算游标 (以 minute_bars 实际最大日期为准) + 记 success
    new_last = await asyncio.to_thread(repo.record_success, stock_code)
    log.info("[quote_sync] %s %s → %d bars (last_loaded=%s, status=success)",
             stock_code, day, n, new_last)
    return {"ok": True, "day": day, "bars": n, "last_loaded_date": new_last}


# change 2026-09-04 (quote-sync-chunk-days): 按 sysconfig 配置的 quote_sync_chunk_days
# 把一段多日拆成 N 天一批的子段, 串行拉 (一天失败就停, 不影响其它天).
# broker 单日 30s idle 超时风险 → 一批 N 天比逐日快, 又避免一次拉太多 broker 拒绝.
async def sync_chunk(stock_code: str, start_day: str, end_day: str,
                     *, chunk_days: int = 0) -> Dict[str, Any]:
    """同步单只证券 [start_day, end_day] 区间, 按 N 天分批串行拉.

    Args:
        stock_code: 证券代码
        start_day: 区间开始 (YYYYMMDD, 含)
        end_day: 区间结束 (YYYYMMDD, 含)
        chunk_days: 每批天数. 0 = 从 sysconfig quote_sync_chunk_days 读 (默认10).

    Returns:
        {ok:bool, start_day:str, end_day:str, days:int, total_bars:int,
         last_loaded_date:str, failed_day:Optional[str]}

    Raises:
        BrokerError: 第一天失败就 re-raise (跟单日语义一致).
    """
    if chunk_days <= 0:
        # 懒加载 sysconfig (启动时 cache 已加载, 直接 get 即可)
        from server.services.sysconfig import get
        chunk_days = get("quote_sync_chunk_days", default=10)
        # 防御边界: 配置坏了/不在合理范围 → 兜底10
        if not (1 <= int(chunk_days) <= 30):
            chunk_days = 10
        chunk_days = int(chunk_days)

    # 区间解析
    sd = datetime.strptime(start_day, "%Y%m%d").date()
    ed = datetime.strptime(end_day, "%Y%m%d").date()
    if sd > ed:
        raise BrokerError(f"INVALID_RANGE: start={start_day} > end={end_day}")

    total_bars = 0
    days_done = 0
    failed_day: str | None = None
    last_loaded: str | None = None
    cur = sd
    while cur <= ed:
        chunk_end_day = min(cur + timedelta(days=chunk_days - 1), ed)
        # 这一批内的每一天串行拉
        d = cur
        while d <= chunk_end_day:
            ds = d.strftime("%Y%m%d")
            try:
                r = await sync_one_day(stock_code, ds)
                total_bars += r["bars"]
                days_done += 1
                last_loaded = r["last_loaded_date"]
            except BrokerError as e:
                failed_day = ds
                log.warning("[quote_sync] %s %s batch chunk 失败: %s (剩余 %s~%s 跳过)",
                            stock_code, ds, e, d.strftime("%Y%m%d"),
                            chunk_end_day.strftime("%Y%m%d"))
                # 一天的 BrokerError 不影响其它天: break 当前 chunk 但不 raise
                break
            d += timedelta(days=1)
        # 即使 chunk 内某天失败, 仍尝试下个 chunk (因为 _cap_day 重算的
        # last_loaded_date 可能已经追上 chunk_end_day); 用户拍板要不要 break
        cur = chunk_end_day + timedelta(days=1)

    if days_done == 0 and failed_day is not None:
        # 第一天就失败 → 跟单日同步一致 re-raise
        raise BrokerError(f"chunk 全部失败: first failed_day={failed_day}")
    log.info("[quote_sync] %s chunk %s~%s 完成: %d days, %d bars, last=%s",
             stock_code, start_day, end_day, days_done, total_bars, last_loaded)
    return {
        "ok": failed_day is None,
        "start_day": start_day,
        "end_day": end_day,
        "days": days_done,
        "total_bars": total_bars,
        "last_loaded_date": last_loaded,
        "failed_day": failed_day,
    }


def read_auto_pending() -> List[str]:
    """列出需要启动自动补全的证券 (auto_sync=1 且 last_loaded_date<昨天)。"""
    y = _yesterday()
    out: List[str] = []
    for cfg in repo.list_configs():
        if not cfg.auto_sync:
            continue
        last = cfg.last_loaded_date or ""
        if last < y:
            out.append(cfg.stock_code)
    return out
