"""
2026-08-11-add-strategy-table-refactor-task.py — DB 迁移脚本

change `strategy-batch-task-model` (task 2.1-2.3):
三层模型: strategy_script → strategy(新) → strategy_task(重构).

1. 新建 `strategy` 表 (strategy_id 自增 PK / user_id / script_id / name / status /
   best_params JSON NULL / 时间戳, INDEX(user_id, script_id))
2. `strategy_task` 加 `strategy_id` + `batch_no` (nullable), 回填:
   - 为每个 strategy_script 按 (user_id, script_id) 建同名 strategy
   - task.script_id → 对应 strategy.strategy_id
   - 按 sweep_id(如有) 分组 / 无则每 task 独立, 分配 task_batch 序号
3. `strategy_task` 删 `script_id` / `best_params` / `sweep_id` / `sweep_total` / `sweep_metric`
4. 加聚合索引 (strategy_id, batch_no, status)

执行:
    python3 server/migrations/2026-08-11-add-strategy-table-refactor-task.py

幂等:
- CREATE TABLE IF NOT EXISTS / 列存在性探测 / 回填仅处理 NULL 行

⚠️ BACKUP 提醒: 跑之前先 dump
    mysqldump -h 192.168.10.2 -P 33066 -u EvTrade -p evtrade_dev strategy_task strategy_script > backup_strategy_20260811.sql
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
    raise RuntimeError("EVTRADE_DB_URL is required (v20 MySQL-only permanent standard).")
if not DATABASE_URL.startswith("mysql"):
    raise RuntimeError(f"Only MySQL is supported (v20 permanent standard). Got URL: {DATABASE_URL[:80]!r}")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

STRATEGY_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS `strategy` (
  `strategy_id` INT NOT NULL AUTO_INCREMENT,
  `user_id` INT NOT NULL,
  `script_id` VARCHAR(64) NOT NULL,
  `name` VARCHAR(64) NOT NULL,
  `status` VARCHAR(16) NOT NULL DEFAULT 'draft',
  `best_params` JSON NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`strategy_id`),
  INDEX `ix_strategy_user_script` (`user_id`, `script_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
"""


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


def _table_exists(conn, table: str) -> bool:
    row = conn.execute(
        text("SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t"),
        {"t": table},
    ).first()
    return row is not None


def _next_batch_no(conn) -> int:
    """mirror repo.next_seq('task_batch') — 迁移脚本不依赖应用包"""
    conn.execute(text("""
        INSERT IGNORE INTO order_no_seq (`seq_name`, `last_value`, `updated_at`)
        VALUES ('task_batch', 10000000, CURRENT_TIMESTAMP)
    """))
    conn.execute(text("""
        UPDATE order_no_seq SET `last_value` = `last_value` + 1, `updated_at` = CURRENT_TIMESTAMP
        WHERE `seq_name` = 'task_batch'
    """))
    return conn.execute(text("SELECT `last_value` FROM order_no_seq WHERE `seq_name` = 'task_batch'")).scalar()


def create_strategy_table(conn) -> None:
    if _table_exists(conn, "strategy"):
        print("  ⏭ strategy table exists, skip")
        return
    conn.execute(text(STRATEGY_TABLE_SQL))
    print("  ✓ created strategy table")


def add_task_columns(conn) -> None:
    if not _column_exists(conn, "strategy_task", "strategy_id"):
        conn.execute(text("ALTER TABLE strategy_task ADD COLUMN strategy_id INT NULL COMMENT '→ strategy.strategy_id (v123)'"))
        print("  ✓ added strategy_task.strategy_id")
    else:
        print("  ⏭ strategy_task.strategy_id exists, skip")
    if not _column_exists(conn, "strategy_task", "batch_no"):
        conn.execute(text("ALTER TABLE strategy_task ADD COLUMN batch_no INT NULL COMMENT '回测/实盘批次号 (v123, 序号表 task_batch)'"))
        print("  ✓ added strategy_task.batch_no")
    else:
        print("  ⏭ strategy_task.batch_no exists, skip")


def backfill_strategies(conn) -> None:
    """为每个 strategy_script 建同名 strategy (按 user_id+script_id 去重, 幂等)."""
    scripts = conn.execute(
        text("SELECT user_id, id, name FROM strategy_script ORDER BY user_id, id")
    ).fetchall()
    inserted = 0
    for s in scripts:
        exists = conn.execute(
            text("SELECT 1 FROM `strategy` WHERE user_id = :u AND script_id = :s LIMIT 1"),
            {"u": s.user_id, "s": s.id},
        ).first()
        if exists:
            continue
        conn.execute(
            text("""
                INSERT INTO `strategy` (`user_id`, `script_id`, `name`, `status`)
                VALUES (:u, :s, :n, 'draft')
            """),
            {"u": s.user_id, "s": s.id, "n": s.name or s.id},
        )
        inserted += 1
    print(f"  ✓ backfilled {inserted} strategy row(s) from strategy_script")


def backfill_task_strategy_id(conn) -> None:
    """task.script_id → strategy_id (仅处理 strategy_id IS NULL 的行, 幂等).

    依赖 script_id 列仍存在 (首次运行); 已 drop 后自动跳过.
    """
    if not _column_exists(conn, "strategy_task", "script_id"):
        print("  ⏭ strategy_task.script_id already dropped, skip backfill")
        return
    rows = conn.execute(
        text("SELECT id, user_id, script_id FROM strategy_task WHERE strategy_id IS NULL")
    ).fetchall()
    updated = 0
    for t in rows:
        matched = conn.execute(
            text("SELECT strategy_id FROM `strategy` WHERE user_id = :u AND script_id = :s LIMIT 1"),
            {"u": t.user_id, "s": t.script_id},
        ).first()
        if matched:
            conn.execute(
                text("UPDATE strategy_task SET strategy_id = :sid WHERE id = :tid"),
                {"sid": matched.strategy_id, "tid": t.id},
            )
            updated += 1
        else:
            print(f"  ⚠ task id={t.id} script_id={t.script_id!r} 无对应 strategy, 保留 strategy_id=NULL")
    print(f"  ✓ backfilled strategy_id on {updated} task(s)")


def backfill_task_batch_no(conn) -> None:
    """batch_no 回填: 按 sweep_id 分组 (无 sweep_id 则每 task 独立), 分配 task_batch 序号.

    sweep_id 列已 drop 后, 退化按每 task 独立一批 (幂等, 仅首次运行有意义).
    """
    has_sweep = _column_exists(conn, "strategy_task", "sweep_id")
    sql = "SELECT id, sweep_id FROM strategy_task WHERE batch_no IS NULL ORDER BY id" if has_sweep \
        else "SELECT id, NULL AS sweep_id FROM strategy_task WHERE batch_no IS NULL ORDER BY id"
    rows = conn.execute(text(sql)).fetchall()
    if not rows:
        print("  ⏭ no task needs batch_no backfill, skip")
        return
    groups = {}
    for r in rows:
        key = r.sweep_id if has_sweep and r.sweep_id else ("single", r.id)
        groups.setdefault(key, []).append(r.id)
    total = 0
    for group_ids in groups.values():
        bn = _next_batch_no(conn)
        placeholders = ", ".join(f":g_{i}" for i in range(len(group_ids)))
        conn.execute(
            text(f"UPDATE strategy_task SET batch_no = :bn WHERE id IN ({placeholders})"),
            {"bn": bn, **{f"g_{i}": gid for i, gid in enumerate(group_ids)}},
        )
        total += len(group_ids)
    print(f"  ✓ assigned batch_no to {total} task(s) across {len(groups)} batch(es)")


def drop_legacy_columns(conn) -> None:
    legacy = ["script_id", "best_params", "sweep_id", "sweep_total", "sweep_metric"]
    for col in legacy:
        if _column_exists(conn, "strategy_task", col):
            conn.execute(text(f"ALTER TABLE strategy_task DROP COLUMN `{col}`"))
            print(f"  ✓ dropped strategy_task.{col}")
        else:
            print(f"  ⏭ strategy_task.{col} already dropped, skip")


def add_batch_index(conn) -> None:
    row = conn.execute(
        text("SELECT 1 FROM INFORMATION_SCHEMA.STATISTICS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='strategy_task' AND INDEX_NAME='ix_strategy_task_batch' LIMIT 1")
    ).first()
    if row:
        print("  ⏭ index ix_strategy_task_batch exists, skip")
        return
    conn.execute(text("ALTER TABLE strategy_task ADD INDEX `ix_strategy_task_batch` (`strategy_id`, `batch_no`, `status`)"))
    print("  ✓ added index ix_strategy_task_batch (strategy_id, batch_no, status)")


def main() -> None:
    db_label = DATABASE_URL.split("@")[-1] if DATABASE_URL else "NONE"
    print(f"[start] strategy 表 + strategy_task 重构 (db={db_label})")

    with engine.begin() as conn:
        create_strategy_table(conn)
        add_task_columns(conn)
        backfill_strategies(conn)
        backfill_task_strategy_id(conn)
        backfill_task_batch_no(conn)
        drop_legacy_columns(conn)
        add_batch_index(conn)

    # ──── 验证 ────
    print("\n[verify] strategy 表:")
    insp = inspect(engine)
    strat_cols = {c["name"] for c in insp.get_columns("strategy")}
    for name in ["strategy_id", "user_id", "script_id", "name", "status", "best_params"]:
        if name in strat_cols:
            print(f"  ✓ strategy.{name}")
        else:
            print(f"  ✗ strategy.{name} MISSING"); sys.exit(1)
    pk = insp.get_pk_constraint("strategy").get("constrained_columns", [])
    if pk != ["strategy_id"]:
        print(f"  ✗ strategy PK 应为 ['strategy_id'], 实际 {pk}"); sys.exit(1)

    print("\n[verify] strategy_task 现状:")
    task_cols = {c["name"] for c in insp.get_columns("strategy_task")}
    for must in ["strategy_id", "batch_no", "id"]:
        if must in task_cols:
            print(f"  ✓ strategy_task.{must}")
        else:
            print(f"  ✗ strategy_task.{must} MISSING"); sys.exit(1)
    for gone in ["script_id", "best_params", "sweep_id", "sweep_total", "sweep_metric"]:
        if gone not in task_cols:
            print(f"  ✓ strategy_task.{gone} dropped")
        else:
            print(f"  ✗ strategy_task.{gone} 仍存在"); sys.exit(1)

    with engine.connect() as conn:
        tasks = conn.execute(text("SELECT id, strategy_id, batch_no FROM strategy_task ORDER BY id")).fetchall()
        for t in tasks:
            print(f"  task id={t.id} strategy_id={t.strategy_id} batch_no={t.batch_no}")

    engine.dispose()
    print("\n[OK] migration 完成 (strategy 表 + strategy_task 重构 + 回填)")


if __name__ == "__main__":
    main()
