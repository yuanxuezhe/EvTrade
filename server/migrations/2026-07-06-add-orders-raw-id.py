"""
2026-07-06-add-orders-raw-id.py — v13 增量迁移（idempotent, SQLAlchemy 双 driver）

变更：orders 表加 raw_id 列（String(8), nullable）
- 用途：cancel-row 写入时存原 order_no，与 user_def="CANCEL:{orig.order_no}" 冗余
- 普通 strategy 委托 raw_id 永远为 NULL
- 旧 orders 数据无破坏（NULL fallback）

幂等性：先查列是否存在，存在则 skip。
v20 MySQL-only：INFORMATION_SCHEMA.COLUMNS 探测（SQLite 永久下线）。

执行：
    # 默认用业务账号 (EVTRADE_DB_URL)；若需 DDL ALTER 设 EVTRADE_DB_ADMIN_URL
    python server/migrations/2026-07-06-add-orders-raw-id.py
"""
import os
import sys
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

# ─────────────── URL 解析（v20 MySQL-only 永久标准 强制 EVTRADE_DB_URL） ───────────────
# REQ-CFG-009 v20: SQLite fallback 永久下线；migration 脚本同样要求显式 EVTRADE_DB_URL。
# 没设 → KeyError，运维必须先 .env 配齐 URL。
try:
    DATABASE_URL = os.environ["EVTRADE_DB_URL"]
except KeyError:
    raise RuntimeError(
        "EVTRADE_DB_URL is required (v20 MySQL-only permanent standard). "
        "Set it in server/.env, e.g. mysql+pymysql://EvTrade:p%40ssw0rd@127.0.0.1:33066/evtrade?charset=utf8mb4"
    )
if not DATABASE_URL.startswith("mysql"):
    raise RuntimeError(
        f"[migration] Only MySQL is supported (v20 permanent standard). Got: {DATABASE_URL[:80]!r}. "
        "SQLite has been permanently disabled."
    )
# ALTER TABLE 需要 DDL；优先 ADMIN_URL，回退业务 URL
ADMIN_URL = os.environ.get("EVTRADE_DB_ADMIN_URL", DATABASE_URL)
if not ADMIN_URL.startswith("mysql"):
    raise RuntimeError(
        f"EVTRADE_DB_ADMIN_URL must be a MySQL URL. Got: {ADMIN_URL[:80]!r}"
    )


def column_exists(conn: "Engine.connect()", table: str, column: str) -> bool:
    """MySQL INFORMATION_SCHEMA 探测 列是否存在."""
    row = conn.execute(text("""
        SELECT 1
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME   = :t
          AND COLUMN_NAME  = :c
        LIMIT 1
    """), {"t": table, "c": column}).first()
    return row is not None


def main():
    admin_engine = create_engine(ADMIN_URL, future=True)
    try:
        with admin_engine.begin() as conn:
            # 第一步：用 admin URL 探测 (admin 需 SELECT on evtrade.*)
            if column_exists(conn, "orders", "raw_id"):
                print("[SKIP] orders.raw_id already exists, no migration needed")
                return

            # 第二步：ALTER TABLE ADD COLUMN（MySQL 不支持 IF NOT EXISTS，已探测过）
            conn.execute(text("ALTER TABLE orders ADD COLUMN raw_id VARCHAR(8) NULL"))

        print("[OK] Added column orders.raw_id (VARCHAR(8), nullable)")

        # 第三步：用业务 URL 验证 (admin 可不验证，但业务账号代表真实业务视角)
        biz_engine = create_engine(DATABASE_URL, future=True)
        try:
            with biz_engine.begin() as conn:
                if not column_exists(conn, "orders", "raw_id"):
                    print("[WARN] column exists via admin but NOT via business URL — check permissions")
                    sys.exit(2)
                print("[VERIFY] column visible via business URL ✓")
        finally:
            biz_engine.dispose()
    finally:
        admin_engine.dispose()


if __name__ == "__main__":
    main()