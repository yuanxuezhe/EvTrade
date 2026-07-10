#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026-07-10-create-stocks-table.py — 创建 stocks 表 (v21 stock-info-crawler)

字段来源:东方财富 API,管理员通过 /admin/sync 手动触发同步。
DDL 幂等(CREATE TABLE IF NOT EXISTS),重复运行安全。

用法:
    python3 server/migrations/2026-07-10-create-stocks-table.py

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

from sqlalchemy import text

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

from sqlalchemy import create_engine

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

DDL = """
CREATE TABLE IF NOT EXISTS stocks (
    stock_code VARCHAR(16) PRIMARY KEY,
    stock_name VARCHAR(64) NOT NULL DEFAULT '',
    industry VARCHAR(64),
    sector VARCHAR(64),
    market VARCHAR(8),
    list_date DATETIME,
    total_share BIGINT NOT NULL DEFAULT 0,
    float_share BIGINT NOT NULL DEFAULT 0,
    market_cap DECIMAL(18,2) NOT NULL DEFAULT 0.00,
    pe_ratio DECIMAL(10,4),
    pb_ratio DECIMAL(10,4),
    intro TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX ix_stocks_industry (industry),
    INDEX ix_stocks_market (market)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""


def main():
    with engine.begin() as conn:
        # DDL
        conn.execute(text(DDL))
        # 验证:查 INFORMATION_SCHEMA 确认表存在 + 行数
        row = conn.execute(text("""
            SELECT TABLE_NAME, TABLE_ROWS, ENGINE
              FROM INFORMATION_SCHEMA.TABLES
             WHERE TABLE_SCHEMA = DATABASE()
               AND TABLE_NAME = 'stocks'
        """)).first()
        if row is None:
            raise RuntimeError("stocks 表创建后未在 INFORMATION_SCHEMA 找到,异常")
        table_name, table_rows, table_engine = row
        print(f"[OK] stocks 表就绪: name={table_name}, rows={table_rows}, engine={table_engine}")
    engine.dispose()


if __name__ == "__main__":
    main()