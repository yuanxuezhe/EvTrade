"""
2026-08-11-add-strategy-sweep-fields.py — DB 迁移脚本 (Phase 3)

change `2026-08-10-strategy-params-sweep-best-live`:
strategy_task 表加 3 列 nullable (sweep_id / sweep_metric / sweep_total),
支持 REQ-SE-008 (sweep) + REQ-SE-009 (live 接 best_params).

执行:
    python3 server/migrations/2026-08-11-add-strategy-sweep-fields.py

幂等:
- INFORMATION_SCHEMA 检测列存在 → 已加则跳过

⚠️ BACKUP 提醒: 跑之前先 dump
    mysqldump -h 192.168.10.2 -P 33066 -u EvTrade -p evtrade strategy_task > backup_20260811.sql

设计: 不依赖 strategy_exec 包, 仅用 SQLAlchemy 跑 SQL
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


NEW_FIELDS = [
    {
        "name": "sweep_id",
        # VARCHAR(32) = uuid4 hex 截 32 位 (sweep_id 用 uuid4().hex[:32] 生成)
        "ddl": "ALTER TABLE strategy_task ADD COLUMN sweep_id VARCHAR(32) NULL DEFAULT NULL",
        "comment": "COMMENT '同一 sweep 多 task 共享, summary task 也带 (用 sweep_total=1 区分)'",
    },
    {
        "name": "sweep_metric",
        "ddl": "ALTER TABLE strategy_task ADD COLUMN sweep_metric VARCHAR(32) NULL DEFAULT NULL",
        "comment": "COMMENT '排序指标名 sharpe / total_return / calmar'",
    },
    {
        "name": "sweep_total",
        "ddl": "ALTER TABLE strategy_task ADD COLUMN sweep_total INT NULL DEFAULT NULL",
        "comment": "COMMENT '同 sweep 的 task 总数 (冗余但查快; 前端直接拿不用 COUNT)'",
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
    """'ALTER TABLE x ADD COLUMN name VARCHAR(32) NULL DEFAULT NULL' → 提取 'VARCHAR(32) NULL DEFAULT NULL'"""
    after_add = ddl.split("ADD COLUMN ", 1)[1]
    parts = after_add.split(" ", 1)
    return parts[1] if len(parts) > 1 else ""


def main() -> None:
    db_label = DATABASE_URL.split("@")[-1] if DATABASE_URL else "NONE"
    print(f"[start] add 3 nullable columns to strategy_task (db={db_label})")
    print(f"  fields: {[f['name'] for f in NEW_FIELDS]}")

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
            print(f"  ✓ added column '{name}' (nullable) with comment")

    # ──── 验证 ────
    print("\n[verify] strategy_task 当前 sweep 相关字段:")
    insp = inspect(engine)
    columns = {c["name"]: c for c in insp.get_columns("strategy_task")}
    new_names = [f["name"] for f in NEW_FIELDS]
    for name in new_names:
        if name in columns:
            c = columns[name]
            print(f"  ✓ {name:15} {str(c['type']):20} nullable={c['nullable']}")
        else:
            print(f"  ✗ {name:15} MISSING (migration failed)")
            sys.exit(1)

    engine.dispose()
    print("\n[OK] migration 完成 (3 nullable columns added)")


if __name__ == "__main__":
    main()
