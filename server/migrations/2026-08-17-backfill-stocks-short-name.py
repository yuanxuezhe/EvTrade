#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026-08-17-backfill-stocks-short-name.py — 回填 stocks.short_name 历史数据

用户指令: "证券信息表 stocks 简称缺失，补充一下"

现状:
  - stocks.short_name 列早已存在（stocks-cache-and-short-name /
    2026-07-12-add-short-name-to-stocks.py）, schema.yml 也有声明
  - 新增/编辑自动派生正常（repo.stocks.create_by_admin / update_by_admin
    内部调用 services.short_name.to_short_name）
  - 但历史存量行（在该列加完之后、未走 create/update 的）
    short_name 仍是 NULL 或空串 → 前端 /api/stocks 列表 / StkPool /
    AdminStockConfig 选股器都看不到简称

本 migration 策略:
  1. 探测 stocks 表 + short_name 列（必须都已存在）
  2. SELECT stock_code, stock_name FROM stocks
     WHERE short_name IS NULL OR short_name = ''
  3. 对每行调用 server.services.short_name.to_short_name(stock_name) 生成新值
  4. UPDATE stocks SET short_name = :s WHERE stock_code = :c
  5. 跳过已填值的（幂等, 不覆盖人工修正）

幂等性:
  - WHERE 过滤 short_name IS NULL OR '' → 已填的行自然不进入 UPDATE 集
  - 重复运行安全（除首次外的 backfill 都是 no-op）

依赖:
  - server/services/short_name.py (REQ-STOCK-007 单一可信源)
  - server/.env EVTRADE_DB_URL (MySQL-only 强制)

用法:
    python3 server/migrations/2026-08-17-backfill-stocks-short-name.py
    python3 server/migrations/2026-08-17-backfill-stocks-short-name.py --dry-run
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

from sqlalchemy import text, create_engine  # noqa: E402

# MySQL-only 强制
DATABASE_URL = os.environ.get("EVTRADE_DB_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "EVTRADE_DB_URL is required (MySQL-only permanent standard). "
        "Set it in server/.env"
    )
if not DATABASE_URL.startswith("mysql"):
    raise RuntimeError(
        f"Only MySQL is supported (permanent standard). Got URL: {DATABASE_URL[:80]!r}"
    )

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

# REQ-STOCK-007 单一可信源：与 server/api/stocks.py / repo.stocks / scripts/backfill_short_name.py 共享
from server.services.short_name import to_short_name  # noqa: E402


def _table_exists(conn, table: str) -> bool:
    row = conn.execute(text("""
        SELECT 1 FROM INFORMATION_SCHEMA.TABLES
         WHERE TABLE_SCHEMA = DATABASE()
           AND TABLE_NAME = :t
         LIMIT 1
    """), {"t": table}).first()
    return row is not None


def _column_exists(conn, table: str, column: str) -> bool:
    row = conn.execute(text("""
        SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
         WHERE TABLE_SCHEMA = DATABASE()
           AND TABLE_NAME   = :t
           AND COLUMN_NAME  = :c
         LIMIT 1
    """), {"t": table, "c": column}).first()
    return row is not None


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill stocks.short_name 历史数据")
    parser.add_argument("--dry-run", action="store_true", help="只打印不 UPDATE")
    args = parser.parse_args()

    print(f"[start] backfill stocks.short_name (dry_run={args.dry_run})")
    print(f"  db: {DATABASE_URL.split('@')[-1]}")

    with engine.begin() as conn:
        # 1. 前置探测: stocks 表 + short_name 列都已存在（先前迁移留下的状态）
        if not _table_exists(conn, "stocks"):
            raise RuntimeError(
                "[migrate] stocks 表不存在,先跑 2026-07-10-create-stocks-table.py"
            )
        if not _column_exists(conn, "stocks", "short_name"):
            raise RuntimeError(
                "[migrate] stocks.short_name 列不存在,先跑 2026-07-12-add-short-name-to-stocks.py"
            )

        # 2. 拉待回填行（已填的自动过滤, 默认不覆盖）
        rows = conn.execute(text("""
            SELECT stock_code, stock_name, short_name
              FROM stocks
             WHERE short_name IS NULL OR short_name = ''
             ORDER BY stock_code
        """)).all()

        total = len(rows)
        print(f"[fetch] 待回填行数: {total}")

        if total == 0:
            print("[skip] stocks.short_name 全部已填, 无需 backfill")
            engine.dispose()
            print("[OK] backfill 完成 (no-op)")
            return

        updated = 0
        warned = 0
        BATCH_LOG = 500

        for i, (code, name, _current) in enumerate(rows, 1):
            short = to_short_name(name)
            if not short:
                warned += 1
                print(f"[warn] {code}: stock_name={name!r} 转拼音失败, 跳过")
                continue

            if args.dry_run:
                print(f"[dry-run] {code} {name!r} → {short}")
            else:
                conn.execute(text(
                    "UPDATE stocks SET short_name = :s WHERE stock_code = :c"
                ), {"s": short, "c": code})

            updated += 1
            if i % BATCH_LOG == 0:
                print(f"[progress] {i}/{total} ({100*i/total:.1f}%)")

        # 3. 验证: 剩余空值应只来自转换失败的行
        remain = conn.execute(text("""
            SELECT COUNT(*) FROM stocks
             WHERE short_name IS NULL OR short_name = ''
        """)).scalar() or 0

    engine.dispose()

    print(f"\n[summary] 待回填={total}, updated={updated}, warned={warned}, 剩余空值={remain}")
    if not args.dry_run and remain > 0:
        print(f"[note] 剩余 {remain} 行为 stock_name 无法转拼音, 已 warn, 不强制写入")
    print("[OK] backfill 完成" if not args.dry_run else "[OK] dry-run 完成")


if __name__ == "__main__":
    main()
