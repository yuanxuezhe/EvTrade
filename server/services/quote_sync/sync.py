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
    """同步单只证券某一天。成功 (含假日空) 返结果; 失败 raise BrokerError。

    Returns: {ok:bool, day:str, bars:int, last_loaded_date:str}
    """
    cfg = repo.get_config(stock_code)
    if cfg is None:
        raise BrokerError(f"NO_CONFIG: {stock_code} 无 quote_sync_config 配置行")

    client = get_his_hq_client()
    await client.connect()
    try:
        rows = await client.fetch_one_day(stock_code, day)
    except BrokerError:
        raise
    except Exception as e:
        log.exception("[quote_sync] fetch_one_day %s %s 异常", stock_code, day)
        raise BrokerError(f"BROKER_ERROR: {e}") from e

    records = [to_record(stock_code, r) for r in rows]
    # 同步 IO 放线程 (broker 拉取已 await, 落库是同步 SQLAlchemy)
    n = await asyncio.to_thread(repo.upsert_minute_bars, records)
    # 成功 (含假日 0 根) 推进游标 — 单调向前
    cur = cfg.last_loaded_date or ""
    if day > cur:
        await asyncio.to_thread(repo.advance_cursor, stock_code, day)
        new_last = day
    else:
        new_last = cur
    log.info("[quote_sync] %s %s → %d bars (last_loaded=%s)",
             stock_code, day, n, new_last)
    return {"ok": True, "day": day, "bars": n, "last_loaded_date": new_last}


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
