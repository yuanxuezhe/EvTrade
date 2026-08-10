"""
2026-08-11-add-backtest-metric-value.py — DB 迁移

strategy_task 表加 backtest_metric_value FLOAT 列:
- 持久化单 run 的指标值 (sharpe → total_return → pnl/initial_cash 回退, 与服务端
  server/services/script_strategy/_convert.py 的 _extract_metric_value 一致)。
- 背景: 列表接口 `SELECT * ... ORDER BY id` 会拖回最大 1.85MB 的 backtest_result
  blob, MySQL 对超大行 filesort 报 1038 'Out of sort memory' → 500。
  持久化该轻量数值后, 列表用列白名单 SELECT 即可同时 (a) 免拖大 blob (b) 保留指标展示。

幂等: 已存在则跳过; 已有行按 backtest_result JSON 回填 (无法解析 → NULL)。

执行:
    python3 server/migrations/2026-08-11-add-backtest-metric-value.py
    # 若运行在另一数据库环境, 用 EVTRADE_DB_URL 覆盖:
    #   EVTRADE_DB_URL="mysql+pymysql://.../evtrade?..." python3 ...
"""

from __future__ import annotations

import json
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

COLUMN_NAME = "backtest_metric_value"


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


def _extract_metric_value(backtest_result) -> float | None:
    """回填用: 必须与 server _convert._extract_metric_value 语义一致."""
    if not backtest_result or not isinstance(backtest_result, dict):
        return None
    # 首选 sharpe, 再 total_return, 最后 pnl/initial_cash
    for key in ("sharpe", "total_return"):
        if backtest_result.get(key) is not None:
            try:
                return float(backtest_result[key])
            except (TypeError, ValueError):
                pass
    pnl = backtest_result.get("pnl")
    cash = backtest_result.get("initial_cash") or 100000.0
    if pnl is not None and cash:
        try:
            return float(pnl) / float(cash)
        except (TypeError, ValueError):
            pass
    return None


def main() -> None:
    print("[start] add backtest_metric_value column to strategy_task")
    print(f"  db: {DATABASE_URL.split('@')[-1] if DATABASE_URL else 'NONE'}")

    with engine.begin() as conn:
        if _column_exists(conn, "strategy_task", COLUMN_NAME):
            print(f"  [skip] column '{COLUMN_NAME}' already exists")
        else:
            conn.execute(text(
                "ALTER TABLE strategy_task ADD COLUMN "
                "backtest_metric_value FLOAT NULL COMMENT '单 run 指标值 (sharpe→total_return→pnl/initial_cash)'"
            ))
            print(f"  [OK] added column '{COLUMN_NAME}'")

        # ──── 回填已有行 (解析 backtest_result, 避免列表再拖大 blob) ────
        rows = conn.execute(text(
            "SELECT id, backtest_result FROM strategy_task "
            "WHERE backtest_result IS NOT NULL AND backtest_result <> ''"
        )).fetchall()
        backfilled = skipped = 0
        for rid, blob in rows:
            try:
                parsed = json.loads(blob) if isinstance(blob, str) else blob
            except (ValueError, TypeError):
                parsed = None
            mv = _extract_metric_value(parsed)
            if mv is None:
                skipped += 1
                continue
            conn.execute(text(
                "UPDATE strategy_task SET backtest_metric_value = :mv WHERE id = :id"
            ), {"mv": mv, "id": rid})
            backfilled += 1
        print(f"  [OK] backfill: {backfilled} rows updated, {skipped} rows skipped (no metric)")

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
