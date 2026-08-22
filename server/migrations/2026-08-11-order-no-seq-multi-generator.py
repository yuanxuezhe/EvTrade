"""
2026-08-11-order-no-seq-multi-generator.py — DB 迁移脚本

change `strategy-batch-task-model` (task 1.1):
order_no_seq 表从单行 (id=1 PK) 泛化为多生成器表 (seq_name PK)。
- 现有行 → seq_name='order_no' (保留 last_value)
- 新增 task_batch 生成器行 (last_value=10000000)
- 删旧 id 列 / 旧主键

执行:
    python3 server/migrations/2026-08-11-order-no-seq-multi-generator.py

幂等:
- INFORMATION_SCHEMA 检测 seq_name 列存在 → 结构变更跳过
- 生成器行用 INSERT IGNORE 保证幂等

⚠️ BACKUP 提醒: 跑之前先 dump
    mysqldump -h 192.168.10.2 -P 33066 -u EvTrade -p evtrade_dev order_no_seq > backup_order_no_seq_20260811.sql
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(HERE)
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "server"))

try:
    from dotenv import load_dotenv
    _ENV_PATH = os.path.join(os.path.dirname(HERE), ".env")
    if os.path.exists(_ENV_PATH):
        load_dotenv(_ENV_PATH, override=False)
except ImportError:
    pass

from sqlalchemy import text, create_engine, inspect

DATABASE_URL = os.environ.get("EVTRADE_DB_URL")
if not DATABASE_URL:
    raise RuntimeError("EVTRADE_DB_URL is required (MySQL-only permanent standard).")
if not DATABASE_URL.startswith("mysql"):
    raise RuntimeError(f"Only MySQL is supported (permanent standard). Got URL: {DATABASE_URL[:80]!r}")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

SEED_LAST_VALUE = 10000000
GENERATORS = ["order_no", "task_batch"]


def _column_exists(conn, table: str, column: str) -> bool:
    row = conn.execute(
        text("""
            SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE()
               AND TABLE_NAME = :t
               AND COLUMN_NAME = :c
             LIMIT 1
        """),
        {"t": table, "c": column},
    ).first()
    return row is not None


def migrate_structure(conn) -> None:
    """单行(id PK) → 多生成器(seq_name PK). 仅在 seq_name 列缺失时执行."""
    if _column_exists(conn, "order_no_seq", "seq_name"):
        print("  ⏭ structure already migrated (seq_name exists), skip")
        return

    # 1) 加 seq_name 列 (先 nullable, 便于回填存量行)
    conn.execute(text("ALTER TABLE order_no_seq ADD COLUMN seq_name VARCHAR(32) NULL"))
    # 2) 存量行回填 seq_name='order_no' (旧表仅 id=1 一行)
    conn.execute(text("UPDATE order_no_seq SET seq_name = 'order_no' WHERE seq_name IS NULL"))
    # 3) 去掉 id 的 AUTO_INCREMENT, 再删旧 PK 与 id 列 (避免 MySQL 1075 约束)
    conn.execute(text("ALTER TABLE order_no_seq MODIFY id INT NOT NULL"))
    conn.execute(text("ALTER TABLE order_no_seq DROP PRIMARY KEY"))
    conn.execute(text("ALTER TABLE order_no_seq DROP COLUMN id"))
    # 4) seq_name 提为主键
    conn.execute(text("ALTER TABLE order_no_seq MODIFY seq_name VARCHAR(32) NOT NULL"))
    conn.execute(text("ALTER TABLE order_no_seq ADD PRIMARY KEY (seq_name)"))
    print("  ✓ structure migrated (single-row → seq_name PK)")


def ensure_generators(conn) -> None:
    """确保 order_no / task_batch 两个生成器行存在 (INSERT IGNORE 幂等)."""
    for name in GENERATORS:
        conn.execute(
            text("""
                INSERT IGNORE INTO order_no_seq (`seq_name`, `last_value`, `updated_at`)
                VALUES (:name, :seed, CURRENT_TIMESTAMP)
            """),
            {"name": name, "seed": SEED_LAST_VALUE},
        )
    print(f"  ✓ generators ensured: {GENERATORS}")


def main() -> None:
    db_label = DATABASE_URL.split("@")[-1] if DATABASE_URL else "NONE"
    print(f"[start] order_no_seq 多生成器泛化 (db={db_label})")

    with engine.begin() as conn:
        migrate_structure(conn)
        ensure_generators(conn)

    # ──── 验证 ────
    print("\n[verify] order_no_seq 当前结构:")
    insp = inspect(engine)
    columns = {c["name"]: c for c in insp.get_columns("order_no_seq")}
    expected = ["seq_name", "last_value", "updated_at"]
    for name in expected:
        if name in columns:
            c = columns[name]
            print(f"  ✓ {name:12} {str(c['type']):20} pk={'seq_name' == name}")
        else:
            print(f"  ✗ {name:12} MISSING (migration failed)")
            sys.exit(1)
    pk = insp.get_pk_constraint("order_no_seq").get("constrained_columns", [])
    if pk != ["seq_name"]:
        print(f"  ✗ PK 应为 ['seq_name'], 实际 {pk}")
        sys.exit(1)

    print("\n[verify] 生成器行:")
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT `seq_name`, `last_value`, `updated_at` FROM order_no_seq ORDER BY seq_name")).fetchall()
    for name in GENERATORS:
        match = [r for r in rows if r.seq_name == name]
        if match:
            print(f"  ✓ {name:12} last_value={match[0].last_value}")
        else:
            print(f"  ✗ {name:12} MISSING (migration failed)")
            sys.exit(1)

    engine.dispose()
    print("\n[OK] migration 完成 (order_no_seq → seq_name PK, 生成器: order_no/task_batch)")


if __name__ == "__main__":
    main()
