#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026-07-12-slim-stocks-table.py — 瘦身 stocks 表 (v23 slim-stocks-table)

用户指令（2026-07-12）: "证券信息表只保留证券代码，证券名称，板块，回转标志，
最小买入数量，买卖单位2，修改表后优化代码适配"

策略:
  1. 先 CREATE TABLE stocks_legacy AS SELECT * FROM stocks
     → 历史 14 字段完整保留到 stocks_legacy 表（不丢弃任何数据）
  2. DROP 9 字段: industry/market/list_date/total_share/float_share/
                 market_cap/pe_ratio/pb_ratio/intro
  3. ADD  3 字段: is_t0_able (BOOL) / min_buy_qty (INT) / trade_unit (INT)
  4. DROP 2 索引:  ix_stocks_industry / ix_stocks_market
  5. 默认值:
       is_t0_able  = FALSE
       min_buy_qty = 100  (A 股整手)
       trade_unit  = 1    (买卖单位默认 1)

幂等性:
  - DROP COLUMN: 靠 INFORMATION_SCHEMA 探测后 DROP（MySQL 8.0 不支持 IF EXISTS 语法）
  - ADD COLUMN: 用 IF NOT EXISTS（MySQL 8.0.29+）
  - CREATE TABLE 备份: 只在 stocks_legacy 不存在时执行
  - DROP INDEX: INFORMATION_SCHEMA 探测后 DROP
  重复运行安全（除首轮外的字段 ADD/DROP 都是 no-op）。

用法:
    python3 server/migrations/2026-07-12-slim-stocks-table.py

依赖: server/.env 含 EVTRADE_DB_URL (v20 MySQL-only 强制)
"""
import os
import sys

# 确保项目根在 sys.path（server/.env 的 load_dotenv 需 server 目录在 path）
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

# v20 MySQL-only 强制:显式读 EVTRADE_DB_URL
DATABASE_URL = os.environ.get("EVTRADE_DB_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "EVTRADE_DB_URL is required (v20 MySQL-only permanent standard). "
        "Set it in server/.env"
    )
if not DATABASE_URL.startswith("mysql"):
    raise RuntimeError(
        f"Only MySQL is supported (v20 permanent standard). Got URL: {DATABASE_URL[:80]!r}"
    )

engine = create_engine(DATABASE_URL, pool_pre_ping=True)


# ─────────────── 备份（幂等） ───────────────
BACKUP_DDL = """
CREATE TABLE IF NOT EXISTS stocks_legacy AS SELECT * FROM stocks WHERE 1=0;
"""


# ─────────────── DROP 9 列（幂等：IF EXISTS） ───────────────
DROP_COLUMNS = [
    "industry",
    "market",
    "list_date",
    "total_share",
    "float_share",
    "market_cap",
    "pe_ratio",
    "pb_ratio",
    "intro",
]


# ─────────────── ADD 3 列（幂等：IF NOT EXISTS） ───────────────
ADD_COLUMNS_DDL = [
    "ADD COLUMN IF NOT EXISTS is_t0_able TINYINT(1) NOT NULL DEFAULT 0",
    "ADD COLUMN IF NOT EXISTS min_buy_qty INT NOT NULL DEFAULT 100",
    "ADD COLUMN IF NOT EXISTS trade_unit INT NOT NULL DEFAULT 1",
]


# ─────────────── DROP 2 索引（幂等：探测后 DROP） ───────────────
DROP_INDEXES = ["ix_stocks_industry", "ix_stocks_market"]


def _info_schema_table_exists(conn, table_name: str) -> bool:
    row = conn.execute(text("""
        SELECT 1 FROM INFORMATION_SCHEMA.TABLES
         WHERE TABLE_SCHEMA = DATABASE()
           AND TABLE_NAME = :t
         LIMIT 1
    """), {"t": table_name}).first()
    return row is not None


def _info_schema_index_exists(conn, table_name: str, index_name: str) -> bool:
    row = conn.execute(text("""
        SELECT 1 FROM INFORMATION_SCHEMA.STATISTICS
         WHERE TABLE_SCHEMA = DATABASE()
           AND TABLE_NAME   = :t
           AND INDEX_NAME   = :n
         LIMIT 1
    """), {"t": table_name, "n": index_name}).first()
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
        # 0. 前置检查：stocks 表必须存在
        if not _info_schema_table_exists(conn, "stocks"):
            raise RuntimeError(
                "[migrate] stocks 表不存在,先跑 2026-07-10-create-stocks-table.py"
            )

        # 1. 备份 stocks → stocks_legacy（仅首次，IF NOT EXISTS 不会覆盖）
        legacy_exists = _info_schema_table_exists(conn, "stocks_legacy")
        if not legacy_exists:
            # 必须先建表（用 stocks 现有 DDL）,再 INSERT
            # MySQL 没有 CREATE TABLE AS ... LIKE；但可以用 CREATE TABLE AS SELECT 一次性建表 + 拷数据
            # IF NOT EXISTS 已经检查过，第一次进入该分支
            conn.execute(text("""
                CREATE TABLE stocks_legacy AS SELECT * FROM stocks
            """))
            print(f"[backup] 创建 stocks_legacy + 拷贝 stocks 当前所有行")
        else:
            print(f"[backup] stocks_legacy 已存在,跳过备份（历史数据已在 legacy 表里）")

        # 2. DROP COLUMN 9 个（INFORMATION_SCHEMA 探测 → DROP,无 IF EXISTS）
        dropped = []
        for col in DROP_COLUMNS:
            if _info_schema_column_exists(conn, "stocks", col):
                conn.execute(text(f"ALTER TABLE stocks DROP COLUMN {col}"))
                dropped.append(col)
        print(f"[drop] 删除 {len(dropped)} 列: {dropped}")

        # 3. ADD COLUMN 3 个（INFORMATION_SCHEMA 探测 → ADD,无 IF NOT EXISTS）
        added = []
        # 把 ADD_COLUMNS_DDL 重写成 dict[col_name → DDL 后缀]
        add_ddl_by_col = {}
        for add_ddl in ADD_COLUMNS_DDL:
            # ddl: "ADD COLUMN IF NOT EXISTS <col_name> <TYPE>..."
            tokens = add_ddl.split()
            col_name = tokens[5]
            # 截取 col_name 后的部分作为 ADD COLUMN 真正的 DDL
            # 拼接: ALTER TABLE stocks ADD COLUMN <col_name> <TYPE>...
            tail_idx = add_ddl.index(col_name) + len(col_name)
            add_ddl_by_col[col_name] = f"ADD COLUMN {col_name}{add_ddl[tail_idx:]}"

        for col_name, add_ddl in add_ddl_by_col.items():
            if not _info_schema_column_exists(conn, "stocks", col_name):
                conn.execute(text(f"ALTER TABLE stocks {add_ddl}"))
                added.append(col_name)
        print(f"[add] 新增 {len(added)} 列: {added}")

        # 4. DROP INDEX 2 个（探测后 DROP，幂等）
        dropped_idx = []
        for idx in DROP_INDEXES:
            if _info_schema_index_exists(conn, "stocks", idx):
                conn.execute(text(f"ALTER TABLE stocks DROP INDEX {idx}"))
                dropped_idx.append(idx)
        print(f"[idx] 删除 {len(dropped_idx)} 索引: {dropped_idx}")

        # 5. 验证：列清单
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
    print("\n[OK] stocks 表瘦身完成")


if __name__ == "__main__":
    main()