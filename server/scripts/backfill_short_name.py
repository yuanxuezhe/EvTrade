#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backfill_short_name.py — 一次性灌入 stocks.short_name 字段 (共享 server.services.short_name.to_short_name)

背景: "后端数据库增加证券简称字段，填入名称拼音首字母，
用来快速通过首字母筛选"

策略:
  1. 读 stocks 表所有行
  2. 用 server.services.short_name.to_short_name() 转每个 stock_name 首字母(大写, ST 前缀保留)
  3. UPDATE stocks SET short_name = ? WHERE stock_code = ?
  4. 跳过已填的(幂等, --force 覆盖)

用法:
    python3 server/scripts/backfill_short_name.py            # 默认灌入空白的
    python3 server/scripts/backfill_short_name.py --force    # 强制覆盖已填的
    python3 server/scripts/backfill_short_name.py --dry-run  # 只打印不 UPDATE

性能:
    - 5529 行实测 ~2s
    - 单条 UPDATE,无事务包裹(失败单条不影响整体)

依赖: server/.env 含 EVTRADE_DB_URL (MySQL-only 强制)

to_short_name 位于 server/services/short_name.py (REQ-STOCK-007), 共享给
create_by_admin / update_by_admin / 本脚本, 算法含 ST 前缀保留
"""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER_DIR = os.path.dirname(HERE)
PROJECT_ROOT = os.path.dirname(SERVER_DIR)
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, SERVER_DIR)

try:
    from dotenv import load_dotenv
    _ENV_PATH = os.path.join(SERVER_DIR, ".env")
    if os.path.exists(_ENV_PATH):
        load_dotenv(_ENV_PATH, override=False)
except ImportError:
    pass

from sqlalchemy import text, create_engine
from server.services.short_name import to_short_name  # 共享函数 (REQ-STOCK-007)
DATABASE_URL = os.environ.get("EVTRADE_DB_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "EVTRADE_DB_URL is required (MySQL-only permanent standard)."
    )
if not DATABASE_URL.startswith("mysql"):
    raise RuntimeError(
        f"Only MySQL is supported (permanent standard). Got URL: {DATABASE_URL[:80]!r}"
    )

engine = create_engine(DATABASE_URL, pool_pre_ping=True)


# 共享函数: from server.services.short_name import to_short_name (上方已 import)
# 删除本地副本, 防止算法漂移 (REQ-STOCK-007)


def main():
    parser = argparse.ArgumentParser(description="Backfill stocks.short_name 字段")
    parser.add_argument("--force", action="store_true", help="覆盖已填的 short_name")
    parser.add_argument("--dry-run", action="store_true", help="只打印不 UPDATE")
    args = parser.parse_args()

    print(f"[start] backfill short_name (force={args.force}, dry_run={args.dry_run})")
    with engine.begin() as conn:
        # 读所有 stocks 行
        sql_filter = "" if args.force else "WHERE short_name IS NULL OR short_name = ''"
        rows = conn.execute(text(f"""
            SELECT stock_code, stock_name, short_name
              FROM stocks
              {sql_filter}
             ORDER BY stock_code
        """)).all()

        total = len(rows)
        print(f"[fetch] 待处理行数: {total}")

        updated = 0
        skipped = 0
        warned = 0
        BATCH_LOG = 500

        for i, (code, name, current) in enumerate(rows, 1):
            short = to_short_name(name)
            if not short:
                warned += 1
                print(f"[warn] {code}: stock_name='{name}' 转拼音失败,跳过")
                continue

            if args.dry_run:
                # 只打印
                print(f"[dry-run] {code} {name!r} → {short}")
                updated += 1
            else:
                # UPDATE
                conn.execute(text(
                    "UPDATE stocks SET short_name = :s WHERE stock_code = :c"
                ), {"s": short, "c": code})
                updated += 1

            # 进度日志
            if i % BATCH_LOG == 0:
                print(f"[progress] {i}/{total} ({100*i/total:.1f}%)")

        print(f"\n[summary] total={total}, updated={updated}, warned={warned}, skipped={skipped}")

    engine.dispose()
    print("[OK] backfill 完成" if not args.dry_run else "[OK] dry-run 完成")


if __name__ == "__main__":
    main()