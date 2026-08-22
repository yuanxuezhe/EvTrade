#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026-07-12-add-short-name-to-stocks.py — 给 stocks 表加 short_name 字段 (stocks-cache-and-short-name)

用户指令: "后端数据库增加证券简称字段，填入名称拼音首字母，
用来快速通过首字母筛选"

策略:
  1. INFORMATION_SCHEMA 探测 stocks.short_name 是否存在
  2. 不存在则 ALTER TABLE stocks ADD COLUMN short_name VARCHAR(16) NULL
  3. 已存在则跳过（幂等）

注:
  - 存量数据 backfill 在 server/scripts/backfill_short_name.py 里
  - 本 migration 只加列,不灌数据(用户"自己去维护"原则,首次灌入用单独脚本)

幂等性:
  - ADD COLUMN: 靠 INFORMATION_SCHEMA 探测(MySQL 8.0 ADD COLUMN IF NOT EXISTS 不支持)
  - 重复运行安全(除首轮外 ADD 是 no-op)

用法:
    python3 server/migrations/2026-07-12-add-short-name-to-stocks.py

依赖: server/.env 含 EVTRADE_DB_URL (MySQL-only 强制)
"""
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

# MySQL-only 强制:显式读 EVTRADE_DB_URL
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


def _info_schema_table_exists(conn, table_name: str) -> bool:
    row = conn.execute(text("""
        SELECT 1 FROM INFORMATION_SCHEMA.TABLES
         WHERE TABLE_SCHEMA = DATABASE()
           AND TABLE_NAME = :t
         LIMIT 1
    """), {"t": table_name}).first()
    return row is not None


def _info_schema_column_exists(conn, table_name: str, column_name: str) -> bool:
    row = conn.execute(text("""
        SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
         WHERE TABLE_SCHEMA = DATABASE()
           AND TABLE_NAME   = :t
           AND COLUMN_NAME  = :c
         LIMIT 1
    """), {"t": table_name, "c": column_name}).first()
    return row is not None


def main():
    with engine.begin() as conn:
        # 前置检查:stocks 表必须存在
        if not _info_schema_table_exists(conn, "stocks"):
            raise RuntimeError(
                "[migrate] stocks 表不存在,先跑 2026-07-10-create-stocks-table.py"
            )

        # 探测 short_name 列是否已存在
        if _info_schema_column_exists(conn, "stocks", "short_name"):
            print("[skip] stocks.short_name 已存在,跳过 ADD (幂等)")
        else:
            # ADD COLUMN short_name VARCHAR(16) NULL
            # 加在 stock_code 之后(同类 VARCHAR 列族),但 MySQL ADD COLUMN 不支持 AFTER,
            # 所以加到表尾(updated_at 之后),业务无影响
            conn.execute(text(
                "ALTER TABLE stocks ADD COLUMN short_name VARCHAR(16) NULL"
            ))
            print("[add] stocks.short_name 新增成功 (VARCHAR(16) NULL)")

        # 验证:列清单
        rows = conn.execute(text("""
            SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_DEFAULT
              FROM INFORMATION_SCHEMA.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE()
               AND TABLE_NAME = 'stocks'
             ORDER BY ORDINAL_POSITION
        """)).all()
        print("\n[verify] stocks 最终字段清单:")
        for col, dtype, nullable, default in rows:
            print(f"  {col:<20} {dtype:<20} nullable={nullable:<3} default={default}")

    engine.dispose()
    print("\n[OK] short_name 字段 migration 完成")


if __name__ == "__main__":
    main()