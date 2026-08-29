#!/usr/bin/env python3
"""
scripts/fix_minute_bars_avg_price.py — 一次性修正 minute_bars.avg_price 单位 (his-quote-backfill)

背景:
  首次 3 年落地 (scripts/fetch_minute_bars.py) 时 avg_price = amount/volume,
  因 A股 volume 单位是「手」(1 手=100 股)、amount 是「元」, 算出的是「元/手」
  (比「元/股」大 100 倍)。正确 VWAP = amount/(volume*100) = 元/股。
  后续 server/services/quote_sync/broker.py 已修正为元/股。

修正:
  UPDATE minute_bars SET avg_price = avg_price/100 WHERE avg_price > 1
  阈值 >1 安全 (当前表仅 159992.SZ ~0.85 元/股, 元/手 > 80, 元/股 < 1; 旧数据
  全部 >1, 新数据全部 <1)。

⚠️ 一次性脚本: 只对「元/手时代」的数据跑一次。默认 dry-run (只统计不写),
   加 --apply 才真正执行。重复 --apply 可能二次 /100 (对 avg_price 仍在 >1 的
   修正后行), 故生产库只 apply 一次。

用法:
  uv run python scripts/fix_minute_bars_avg_price.py            # dry-run
  uv run python scripts/fix_minute_bars_avg_price.py --apply    # 真改
"""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> None:
    from dotenv import load_dotenv
    from sqlalchemy import create_engine, text

    load_dotenv(ROOT / "server" / ".env")
    db_url = os.environ.get("EVTRADE_DB_URL")
    if not db_url:
        print("ERROR: EVTRADE_DB_URL 未设置 (server/.env)", file=sys.stderr)
        sys.exit(1)

    parser = argparse.ArgumentParser(description="修正 minute_bars.avg_price 元/手 → 元/股")
    parser.add_argument("--apply", action="store_true", help="真执行 (默认 dry-run)")
    args = parser.parse_args()

    engine = create_engine(db_url, pool_pre_ping=True)
    with engine.connect() as conn:
        affected = conn.execute(text("SELECT COUNT(*) FROM minute_bars WHERE avg_price > 1")).scalar()
        sample = conn.execute(
            text("SELECT stime, avg_price FROM minute_bars WHERE avg_price > 1 ORDER BY stime DESC LIMIT 3")
        ).fetchall()
    print(f"将修正行数 (avg_price>1): {affected}")
    for s in sample:
        print(f"  例: stime={s[0]}  avg_price={s[1]:.4f} → {s[1]/100:.4f}")

    if not args.apply:
        print("\n[dry-run] 未修改。加 --apply 真执行。")
        return
    if affected == 0:
        print("\n无可修正行 (avg_price>1 为 0), 退出。")
        return

    with engine.begin() as conn:
        r = conn.execute(text("UPDATE minute_bars SET avg_price = avg_price/100 WHERE avg_price > 1"))
        print(f"\n[applied] 已修正 {r.rowcount} 行 avg_price /= 100")
    engine.dispose()


if __name__ == "__main__":
    main()
