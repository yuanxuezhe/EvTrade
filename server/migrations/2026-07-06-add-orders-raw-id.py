"""
2026-07-06-add-orders-raw-id.py — v13 增量迁移（idempotent, SQLAlchemy 双 driver）

变更：orders 表加 raw_id 列（String(8), nullable）
- 用途：cancel-row 写入时存原 order_no，与 user_def="CANCEL:{orig.order_no}" 冗余
- 普通 strategy 委托 raw_id 永远为 NULL
- 旧 orders 数据无破坏（NULL fallback）

幂等性：先查列是否存在，存在则 skip。
SQLite + MySQL 双 driver 兼容（SQLAlchemy 元数据探测）。

执行：
    # 默认用业务账号 (EVTRADE_DB_URL)；若需 DDL ALTER 设 EVTRADE_DB_ADMIN_URL
    python server/migrations/2026-07-06-add-orders-raw-id.py
"""
import os
import sys
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

# ─────────────── URL 解析（同 infra/db.py） ───────────────
DEFAULT_URL = "sqlite:///./evtrade.db"
DATABASE_URL = os.environ.get("EVTRADE_DB_URL", DEFAULT_URL)
# ALTER TABLE 需要 DDL；优先 ADMIN_URL，回退业务 URL
ADMIN_URL = os.environ.get("EVTRADE_DB_ADMIN_URL", DATABASE_URL)


def column_exists(conn: "Engine.connect()", table: str, column: str) -> bool:
    """跨 driver 探测 列是否存在."""
    if conn.dialect.name == "mysql":
        row = conn.execute(text("""
            SELECT 1
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME   = :t
              AND COLUMN_NAME  = :c
            LIMIT 1
        """), {"t": table, "c": column}).first()
        return row is not None
    # SQLite + 其它
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return any(r[1] == column for r in rows)


def main():
    admin_engine = create_engine(ADMIN_URL, future=True)
    try:
        with admin_engine.begin() as conn:
            # 第一步：用 admin URL 探测 (admin 需 SELECT on evtrade.*)
            if column_exists(conn, "orders", "raw_id"):
                print("[SKIP] orders.raw_id already exists, no migration needed")
                return

            # 第二步：ALTER TABLE ADD COLUMN
            # MySQL: ADD COLUMN 不支持 IF NOT EXISTS，需先探测
            # SQLite: ALTER TABLE ADD COLUMN 也不支持 IF NOT EXISTS
            # 上面 column_exists 已把"存在"排除，直接执行
            if conn.dialect.name == "mysql":
                conn.execute(text("ALTER TABLE orders ADD COLUMN raw_id VARCHAR(8) NULL"))
            else:
                conn.execute(text("ALTER TABLE orders ADD COLUMN raw_id VARCHAR(8)"))

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