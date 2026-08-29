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
    """新增 quote_sync_config 行, 返写入的 Row。

    last_loaded_date 自动初始化 = MIN(昨天, COALESCE(MAX(minute_bars 该标日期), start_date))
    (按已有 minute_bars 记录, 从最后日期+1 续补)。
    """
    last = _init_last_loaded(stock_code, start_date)
    return QuoteSyncConfig.upsert_one(
        {
            "stock_code": stock_code,
            "start_date": start_date,
            "end_date": end_date,
            "last_loaded_date": last,
            "auto_sync": 1 if auto_sync else 0,
            "status": "idle",  # 显式写, 避免 base upsert 对 NOT NULL 缺省列自动填 ""
            "error_msg": "",
        },
        return_row=True,
    )


def _init_last_loaded(stock_code: str, start_date: str) -> str:
    """新配置初始游标 =「已落地数据的最后日期」语义:
    - 已有 minute_bars 数据 → MAX(该标 stime 日期) (续补从它+1)
    - 无数据 → start_date 前一天 (使 next = start_date 当天, 不漏首日)
    已有数据情况封顶昨天 (今天 1m 不全)。
    """
    from datetime import datetime, timedelta
    yesterday = _yesterday()
    max_day = ""
    try:
        engine = get_engine()
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT MAX(LEFT(stime,8)) FROM minute_bars WHERE stock_code=:c"),
                {"c": stock_code},
            ).fetchone()
            max_day = (row[0] or "") if row else ""
    except Exception:
        log.exception("_init_last_loaded: 查 minute_bars 最大日期失败, 按无数据处理 %s", stock_code)
    if max_day:
        return min(max_day, yesterday)
    # 无数据: 游标 = start_date 前一天 → next 补 start_date 当天
    return (datetime.strptime(start_date, "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d")


def _yesterday() -> str:
    from datetime import datetime, timedelta
    return (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")


def recalc_last_loaded(stock_code: str) -> str:
    """根据 minute_bars 已有记录重算「当前同步到的日期」= 该证券实际最大 stime 日期。

    操作记录语义: 每次同步后调用, 让 last_loaded_date 始终反映真实落地数据的最后日期
    (假日/周末没数据就不推进, 而非盲目向前)。无数据返 ''。
    """
    engine = get_engine()
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT MAX(LEFT(stime,8)) FROM minute_bars WHERE stock_code=:c"),
                {"c": stock_code},
            ).fetchone()
        return (row[0] or "") if row else ""
    except Exception:
        log.exception("recalc_last_loaded: 查 minute_bars 失败 %s", stock_code)
        return ""


def record_success(stock_code: str) -> str:
    """成功操作记录: 重算 last_loaded_date + status=success + 清 error_msg + 更新 updated_at。
    返重算后的 last_loaded_date。"""
    from datetime import datetime
    last = recalc_last_loaded(stock_code)
    QuoteSyncConfig.update_one(
        {"last_loaded_date": last, "status": "success", "error_msg": "",
         "updated_at": datetime.now()},
        stock_code=stock_code,
    )
    return last


def record_failure(stock_code: str, error_msg: str) -> None:
    """失败操作记录: status=failed + error_msg (last_loaded_date 不动, 下次续跑从它+1)。"""
    from datetime import datetime
    QuoteSyncConfig.update_one(
        {"status": "failed", "error_msg": (error_msg or "")[:255],
         "updated_at": datetime.now()},
        stock_code=stock_code,
    )


def list_configs() -> List[Row]:
    return QuoteSyncConfig.query_all("asc")


def update_cfg(stock_code: str, data: Dict[str, Any]) -> None:
    """改配置非主键列 (auto_sync / end_date)。data 不得含 stock_code。"""
    QuoteSyncConfig.update_one(data, stock_code=stock_code)


def get_config(stock_code: str) -> Optional[Row]:
    return QuoteSyncConfig.query_one(stock_code=stock_code)


def delete_config(stock_code: str) -> bool:
    return QuoteSyncConfig.delete_one(stock_code=stock_code)
