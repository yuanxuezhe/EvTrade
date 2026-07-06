"""
2026-07-06-add-orders-raw-id.py — v13 增量迁移（idempotent）

变更：orders 表加 raw_id 列（String(8), nullable）
- 用途：cancel-row 写入时存原 order_no，与 user_def="CANCEL:{orig.order_no}" 冗余
- 普通 strategy 委托 raw_id 永远为 NULL
- 旧 orders 数据无破坏（NULL fallback）

幂等性：先查列是否存在，存在则 skip。SQLite ≥ 3.21 兼容（手写 SQL，不依赖 Alembic）。

执行：python server/migrations/2026-07-06-add-orders-raw-id.py
"""
import sqlite3
import os
import sys


def column_exists(cursor, table: str, column: str) -> bool:
    """检查表 + 列是否存在。"""
    cursor.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cursor.fetchall())


def main():
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "evtrade.db")
    if not os.path.exists(db_path):
        print(f"[ERROR] DB not found: {db_path}")
        sys.exit(1)
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        if column_exists(cur, "orders", "raw_id"):
            print("[SKIP] orders.raw_id already exists, no migration needed")
            return
        # ALTER TABLE ADD COLUMN；nullable 无 DEFAULT，旧数据自动 NULL
        cur.execute("ALTER TABLE orders ADD COLUMN raw_id VARCHAR(8)")
        conn.commit()
        print(f"[OK] Added column orders.raw_id (VARCHAR(8), nullable)")
        # 验证
        if not column_exists(cur, "orders", "raw_id"):
            raise RuntimeError("Migration failed: raw_id column still missing")
        print("[OK] Verified: orders.raw_id present")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
