"""
2026-08-09-strategy-task-exec-fields.py — DB 迁移脚本 (Phase 4)

change `2026-08-09-strategy-exec-service`:
strategy_task 表加 3 字段 (execution_service / execution_pid / version)
- execution_service: 任务执行服务标识 ('evtrade' / 'strategy_exec')
- execution_pid: strategy_exec 进程 pid (用于排查)
- version: 乐观锁 (防双服务并发写)

幂等: 已存在则跳过

执行:
    python3 server/migrations/2026-08-09-strategy-task-exec-fields.py

⚠️ BACKUP 提醒:
    mysqldump -h 192.168.10.2 -P 33066 -u EvTrade -p evtrade strategy_task > backup_20260809.sql
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "server"))

try:
    from dotenv import load_dotenv
    # HERE = server/migrations/ → .env 在 server/.env
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
    raise RuntimeError(f"Only MySQL is supported. Got URL: {DATABASE_URL[:80]!r}")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)


NEW_FIELDS = [
    {
        "name": "execution_service",
        "ddl": "ALTER TABLE strategy_task ADD COLUMN execution_service VARCHAR(16) NOT NULL DEFAULT 'evtrade'",
        "comment": "COMMENT '执行服务标识 (evtrade / strategy_exec)'",
    },
    {
        "name": "execution_pid",
        "ddl": "ALTER TABLE strategy_task ADD COLUMN execution_pid INT NULL DEFAULT NULL",
        "comment": "COMMENT 'strategy_exec 进程 pid (用于排查)'",
    },
    {
        "name": "version",
        "ddl": "ALTER TABLE strategy_task ADD COLUMN version INT NOT NULL DEFAULT 0",
        "comment": "COMMENT '乐观锁 (UPDATE WHERE version 等于当前值)'",
    },
]


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
    """'ALTER TABLE x ADD COLUMN name VARCHAR(16) NOT NULL DEFAULT ...' → 提取 'VARCHAR(16) NOT NULL DEFAULT ...'"""
    after_add = ddl.split("ADD COLUMN ", 1)[1]
    # 去掉列名前缀 (name + 空格)
    parts = after_add.split(" ", 1)
    return parts[1] if len(parts) > 1 else ""


def main() -> None:
    print("[start] add 3 columns to strategy_task")
    print(f"  db: {DATABASE_URL.split('@')[-1] if DATABASE_URL else 'NONE'}")

    with engine.begin() as conn:
        for field in NEW_FIELDS:
            name = field["name"]
            ddl = field["ddl"]
            comment = field["comment"]
            if _column_exists(conn, "strategy_task", name):
                print(f"  ⏭ column '{name}' already exists, skip")
                continue
            # 1) ADD COLUMN
            conn.execute(text(ddl))
            # 2) MODIFY 加 COMMENT
            col_type = _extract_type(ddl)
            comment_sql = comment.replace("COMMENT=", "COMMENT ")
            sql = f"ALTER TABLE strategy_task MODIFY COLUMN `{name}` {col_type} {comment_sql}"
            conn.execute(text(sql))
            print(f"  ✓ added column '{name}' with comment")

    # ──── 验证 ────
    print("\n[verify] strategy_task 当前字段:")
    insp = inspect(engine)
    columns = insp.get_columns("strategy_task")
    for c in columns:
        marker = "  ←NEW" if c["name"] in [f["name"] for f in NEW_FIELDS] else ""
        print(f"  {c['name']:25} {str(c['type']):20} nullable={c['nullable']}{marker}")

    engine.dispose()
    print("\n[OK] migration 完成")


if __name__ == "__main__":
    main()