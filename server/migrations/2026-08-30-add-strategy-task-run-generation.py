"""
2026-08-30-add-strategy-task-run-generation.py — DB 迁移脚本

change `2026-08-30-sweep-worker-queue`:
strategy_task 表加 1 列 run_generation (INT NOT NULL DEFAULT 0),
兼作回测任务的**代际 + 重跑计数器**, 供 worker 队列的堵塞自愈用:
- worker 原子领取 (claim) 某 queued task 时 run_generation + 1
- 该 task 的 progress / result / 终态写都带 WHERE run_generation = 本次代际
- 孤儿线程 (被复位重跑后仍后台跑的旧 to_thread 线程) 晚到的写因代际不匹配 → no-op
- run_generation > backtest_max_retries → 标 failed, 防无限重跑

执行:
    uv run python server/migrations/2026-08-30-add-strategy-task-run-generation.py

幂等:
- INFORMATION_SCHEMA 检测列存在 → 已加则跳过

⚠️ BACKUP 提醒: 跑之前先 dump
    mysqldump -h <host> -P <port> -u <user> -p evtrade strategy_task > backup_20260830.sql

设计: 不依赖 strategy_exec 包, 仅用 SQLAlchemy 跑 SQL; 只 ADD 1 列, 不动现有列/数据
(存量 task run_generation=0, 无影响)
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


NEW_FIELD = {
    "name": "run_generation",
    "ddl": "ALTER TABLE strategy_task ADD COLUMN run_generation INT NOT NULL DEFAULT 0",
    "comment": "COMMENT '回测任务代际+重跑计数 (worker 队列堵塞自愈: claim+1, 写带 WHERE 代际, 超上限标 failed)'",
}


def _column_exists(conn, table: str, column: str) -> bool:
    """查 INFORMATION_SCHEMA 检测列是否存在 (MySQL)"""
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


def _extract_type(ddl: str) -> str:
    """'ALTER TABLE x ADD COLUMN name INT NOT NULL DEFAULT 0' → 提取 'INT NOT NULL DEFAULT 0'"""
    after_add = ddl.split("ADD COLUMN ", 1)[1]
    parts = after_add.split(" ", 1)
    return parts[1] if len(parts) > 1 else ""


def main() -> None:
    db_label = DATABASE_URL.split("@")[-1] if DATABASE_URL else "NONE"
    print(f"[start] add run_generation to strategy_task (db={db_label})")

    with engine.begin() as conn:
        name = NEW_FIELD["name"]
        ddl = NEW_FIELD["ddl"]
        comment = NEW_FIELD["comment"]
        if _column_exists(conn, "strategy_task", name):
            print(f"  skip: column '{name}' already exists")
        else:
            conn.execute(text(ddl))
            col_type = _extract_type(ddl)
            comment_sql = comment.replace("COMMENT=", "COMMENT ")
            sql = f"ALTER TABLE strategy_task MODIFY COLUMN `{name}` {col_type} {comment_sql}"
            conn.execute(text(sql))
            print(f"  added column '{name}' (INT NOT NULL DEFAULT 0) with comment")

    # ──── 验证 ────
    print("\n[verify] strategy_task.run_generation:")
    insp = inspect(engine)
    columns = {c["name"]: c for c in insp.get_columns("strategy_task")}
    name = NEW_FIELD["name"]
    if name in columns:
        c = columns[name]
        print(f"  OK {name:15} {str(c['type']):20} nullable={c['nullable']} default={c.get('default')}")
    else:
        print(f"  MISSING {name} (migration failed)")
        sys.exit(1)

    engine.dispose()
    print("\n[OK] migration 完成 (run_generation added)")


if __name__ == "__main__":
    main()
