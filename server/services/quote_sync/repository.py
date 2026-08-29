"""
server/services/quote_sync/repository.py — minute_bars / quote_sync_config 数据访问

薄封装 TableBase, 给 sync 核心用。写 minute_bars 走批量 upsert (幂等),
读/写 quote_sync_config 走 TableBase 标准方法。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from server.tables import MinuteBars, QuoteSyncConfig
from server.tables.base import get_engine, Row

log = logging.getLogger(__name__)

_MINUTE_BARS_UPSERT = text(
    "INSERT INTO minute_bars "
    "(stock_code, stime, open, close, high, low, avg_price, volume) "
    "VALUES (:stock_code, :stime, :open, :close, :high, :low, :avg_price, :volume) "
    "ON DUPLICATE KEY UPDATE open=VALUES(open), close=VALUES(close), "
    "high=VALUES(high), low=VALUES(low), avg_price=VALUES(avg_price), volume=VALUES(volume)"
)


def upsert_minute_bars(records: List[Dict[str, Any]]) -> int:
    """批量 upsert minute_bars (executemany, 幂等)。返写入行数 (0 行返 0)。"""
    if not records:
        return 0
    clean = [r for r in records if r.get("stime")]
    if not clean:
        return 0
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(_MINUTE_BARS_UPSERT, clean)
    return len(clean)


def add_config(stock_code: str, start_date: str, end_date: str, auto_sync: int) -> Row:
    """新增 quote_sync_config 行 (last_loaded_date 由调用方先算好传入 via 第 5 参? 不, 内部初始化)。

    last_loaded_date 初始化 = MIN(昨天, COALESCE(MAX(minute_bars 该标日期), start_date))。
    """
    last = _init_last_loaded(stock_code, start_date)
    return QuoteSyncConfig.upsert_one(
        {
            "stock_code": stock_code,
            "start_date": start_date,
            "end_date": end_date,
            "last_loaded_date": last,
            "auto_sync": 1 if auto_sync else 0,
        }
    )


def _init_last_loaded(stock_code: str, start_date: str) -> str:
    """新配置的初始游标: 已落地数据的最大日期, 否则 start_date, 封顶昨天。"""
    from datetime import datetime
    engine = get_engine()
    yesterday = _yesterday()
    max_day = ""
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT MAX(LEFT(stime,8)) FROM minute_bars WHERE stock_code=:c"),
                {"c": stock_code},
            ).fetchone()
            max_day = row[0] or "" if row else ""
    except Exception:
        log.exception("_init_last_loaded: 查 minute_bars 最大日期失败, 用 start_date")
    candidate = max_day or start_date
    return min(yesterday, candidate) if candidate else start_date


def _yesterday() -> str:
    from datetime import datetime, timedelta
    return (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")


def advance_cursor(stock_code: str, day: str) -> None:
    """成功同步一天后推进游标 (单调向前, 不后退)。"""
    existing = QuoteSyncConfig.query_one(stock_code=stock_code)
    if existing is None:
        log.warning("advance_cursor: %s 无配置行, 跳过", stock_code)
        return
    cur = existing.last_loaded_date or ""
    if day > cur:
        QuoteSyncConfig.update_one({"last_loaded_date": day}, stock_code=stock_code)


def list_configs() -> List[Row]:
    return QuoteSyncConfig.query_all("asc")


def update_cfg(stock_code: str, data: Dict[str, Any]) -> None:
    """改配置非主键列 (auto_sync / end_date)。data 不得含 stock_code。"""
    QuoteSyncConfig.update_one(data, stock_code=stock_code)


def get_config(stock_code: str) -> Optional[Row]:
    return QuoteSyncConfig.query_one(stock_code=stock_code)


def delete_config(stock_code: str) -> bool:
    return QuoteSyncConfig.delete_one(stock_code=stock_code)
