#!/usr/bin/env python3
"""
scripts/fetch_minute_bars.py — 拉 broker 分钟 K 线落地 minute_bars 表

📌 change 2026-09-03 unify-his-hq-broker-client:
所有历史行情拉取统一走 strategy_exec.market_data.his_hq_client (公共 client).
本脚本只负责: 按日 chunk + 调公共 client + upsert minute_bars + + 同步 last_loaded.

用法:
    uv run python scripts/fetch_minute_bars.py --stock 159992.SZ \\
        --start 20230830 --end 20260901

落库 DB: 读 server/.env 的 EVTRADE_DB_URL (当前 = 生产 evtrade).
空 chunk (早期年份 broker 无数据) → warning 跳过, 不 raise, 结尾报告.
"""
import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "strategy_exec"))

from dotenv import load_dotenv  # noqa: E402

from strategy_exec.market_data.his_hq_client import (  # noqa: E402
    DEFAULT_FIELDS,  # stime,open,high,low,close,volume,amount (period 写死 1m)
    HisHqClient,
    to_record,
)
# _iter_chunks 在 hq_history.py (chunked fetch 调度), 公共 client 不重复实现
from strategy_exec.market_data.hq_history import _iter_chunks  # noqa: E402

log = logging.getLogger("fetch_minute_bars")


async def fetch_one_day(client: HisHqClient, stock: str, day: str) -> list:
    """单日 1m fetch (走公共 client). 返 List[broker bar dict]."""
    return await client.fetch_bars(stock, day, day, fields=DEFAULT_FIELDS)


def upsert(engine, stock: str, bars: list) -> int:
    """批量 upsert 到 minute_bars (executemany + ON DUPLICATE KEY UPDATE, 幂等)."""
    from sqlalchemy import text
    if not bars:
        return 0
    recs = [r for r in (to_record(stock, b) for b in bars) if r["stime"]]
    if not recs:
        return 0
    sql = text(
        "INSERT INTO minute_bars "
        "(stock_code, stime, open, close, high, low, avg_price, volume) "
        "VALUES (:stock_code, :stime, :open, :close, :high, :low, :avg_price, :volume) "
        "ON DUPLICATE KEY UPDATE open=VALUES(open), close=VALUES(close), "
        "high=VALUES(high), low=VALUES(low), avg_price=VALUES(avg_price), volume=VALUES(volume)"
    )
    with engine.begin() as conn:
        conn.execute(sql, recs)
    return len(recs)


def update_progress(engine, stock: str, day: str, bars_n: int) -> None:
    """同步进度: 更新 quote_sync_config.last_loaded_date (空跑不更新)."""
    if bars_n == 0:
        return  # 空日不推进游标 (broker 0 行 → 数据最大日期不变)
    from sqlalchemy import text
    from datetime import datetime
    y = (datetime.now().date()).strftime("%Y%m%d")  # 实际上要 last_loaded_date = 该日
    with engine.begin() as conn:
        # last_loaded_date = 该次成功的 day (broker 实 际有数据的天)
        conn.execute(
            text("UPDATE quote_sync_config SET last_loaded_date = GREATEST(last_loaded_date, :d) "
                 "WHERE stock_code = :s"),
            {"d": day, "s": stock},
        )


def run(args) -> None:
    load_dotenv(ROOT / "server" / ".env")
    from sqlalchemy import create_engine
    db_url = os.environ.get("EVTRADE_DB_URL")
    if not db_url:
        log.error("EVTRADE_DB_URL 未设置 (server/.env)")
        sys.exit(1)
    engine = create_engine(db_url, pool_pre_ping=True)

    client = HisHqClient()

    async def _go() -> int:
        await client.connect()
        chunks = _iter_chunks(args.start, args.end, args.chunk_days)
        log.info("stock=%s %s~%s → %d chunks (chunk_days=%d)",
                 args.stock, args.start, args.end, len(chunks), args.chunk_days)
        total = 0
        empty = 0
        for i, (cs, ce) in enumerate(chunks, 1):
            bars = await fetch_one_day(client, args.stock, cs)
            n = upsert(engine, args.stock, bars)
            update_progress(engine, args.stock, cs, n)
            total += n
            if n == 0:
                empty += 1
            log.info("chunk %d/%d %s~%s → %d rows (累计 %d)",
                     i, len(chunks), cs, ce, n, total)
        await client.close()
        log.info("DONE stock=%s total=%d rows, empty_chunks=%d/%d",
                 args.stock, total, empty, len(chunks))
        return total

    try:
        asyncio.run(_go())
    finally:
        engine.dispose()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        datefmt="%H:%M:%S")
    p = argparse.ArgumentParser(description="拉 broker 分钟 K 线落地 minute_bars")
    p.add_argument("--stock", default="159992.SZ")
    p.add_argument("--start", required=True, help="YYYYMMDD")
    p.add_argument("--end", required=True, help="YYYYMMDD")
    p.add_argument("--chunk-days", type=int, default=10)
    args = p.parse_args()
    run(args)


if __name__ == "__main__":
    main()