"""
2026-08-11-add-task-metric.py — DB 迁移

strategy_task 表加 metric VARCHAR(16) 列 (批次排序指标):
- 批次创建时落库 (sweep: top1 排序指标; single/live: 无实际意义但一并存默认 'sharpe')。
- 背景: 批次列表支持「重测」, 重测需忠实还原原批次的 sweep 排序指标 (sharpe/total_return/calmar),
  否则会用默认 sharpe 排序, 选出的 best_params 可能和原批次不一致。

幂等: 已存在则跳过; 已有行 metric IS NULL → 回填 'sharpe' (老批次无记录, 用默认)。

执行:
    python3 server/migrations/2026-08-11-add-task-metric.py
    # 若运行在另一数据库环境, 用 EVTRADE_DB_URL 覆盖:
    #   EVTRADE_DB_URL="mysql+pymysql://.../evtrade?..." python3 ...
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

from sqlalchemy import text, create_engine, inspect  # noqa: E402

DATABASE_URL = os.environ.get("EVTRADE_DB_URL")
if not DATABASE_URL:
    raise RuntimeError("EVTRADE_DB_URL is required (v20 MySQL-only permanent standard).")
if not DATABASE_URL.startswith("mysql"):
    raise RuntimeError(f"Only MySQL is supported. Got URL: {DATABASE_URL[:80]!r}")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

COLUMN_NAME = "metric"


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


def main() -> None:
    print("[start] add metric column to strategy_task")
    print(f"  db: {DATABASE_URL.split('@')[-1] if DATABASE_URL else 'NONE'}")

    with engine.begin() as conn:
        if _column_exists(conn, "strategy_task", COLUMN_NAME):
            print(f"  [skip] column '{COLUMN_NAME}' already exists")
        else:
            conn.execute(text(
                "ALTER TABLE strategy_task ADD COLUMN "
                "metric VARCHAR(16) NULL COMMENT '批次排序指标 (sweep top1 选择, 重测还原用)' "
                "AFTER batch_no"
            ))
            print(f"  [OK] added column '{COLUMN_NAME}'")

        # ──── 回填老批次: 无记录 → 'sharpe' (默认排序指标) ────
        result = conn.execute(text(
            "UPDATE strategy_task SET metric = 'sharpe' WHERE metric IS NULL"
        ))
        print(f"  [OK] backfill: {result.rowcount} rows set metric='sharpe'")

    # ──── 验证 ────
    print("\n[verify] strategy_task 当前字段:")
    insp = inspect(engine)
    columns = insp.get_columns("strategy_task")
    for c in columns:
        marker = "  <NEW>" if c["name"] == COLUMN_NAME else ""
        print(f"  {c['name']:25} {str(c['type']):20} nullable={c['nullable']}{marker}")

    engine.dispose()
    print("\n[DONE] migration 完成")


if __name__ == "__main__":
    main()
