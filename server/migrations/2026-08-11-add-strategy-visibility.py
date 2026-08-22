"""
2026-08-11-add-strategy-visibility.py — DB 迁移

strategy 表加 2 列:
- is_public TINYINT NOT NULL DEFAULT 0   策略级可见性: 0=私有(默认) 1=公开(列表可见, 供策略下单选择)
- stock_code VARCHAR(16) NULL            策略绑定标的 (新建时必填, 只针对此标的回测)

幂等: 已存在则跳过。存量行 stock_code=NULL → 回测回退用请求的 stock_code (旧行为)。
仿 2026-08-11-add-task-metric.py 的 INFORMATION_SCHEMA 检查模式。

执行:
    python3 server/migrations/2026-08-11-add-strategy-visibility.py
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "server"))

try:
    from dotenv import load_dotenv
    _ENV_PATH = os.path.join(os.path.dirname(HERE), ".env")
    if os.path.exists(_ENV_PATH):
        load_dotenv(_ENV_PATH, override=False)
except ImportError:
    pass

from sqlalchemy import text, create_engine, inspect  # noqa: E402

DATABASE_URL = os.environ.get("EVTRADE_DB_URL")
if not DATABASE_URL:
    raise RuntimeError("EVTRADE_DB_URL is required (MySQL-only permanent standard).")
if not DATABASE_URL.startswith("mysql"):
    raise RuntimeError(f"Only MySQL is supported. Got URL: {DATABASE_URL[:80]!r}")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

COLS = [
    ("is_public",
     "TINYINT NOT NULL DEFAULT 0 "
     "COMMENT '是否公开: 0=私有(默认) 1=公开(列表可见, 供策略下单选择)' AFTER status"),
    ("stock_code",
     "VARCHAR(16) NULL COMMENT '策略绑定标的 (新建时必填, 只针对此标的回测)' AFTER is_public"),
]


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
    print("[start] add strategy visibility columns (is_public / stock_code)")
    print(f"  db: {DATABASE_URL.split('@')[-1] if DATABASE_URL else 'NONE'}")

    with engine.begin() as conn:
        for col, ddl in COLS:
            if _column_exists(conn, "strategy", col):
                print(f"  [skip] column '{col}' already exists")
            else:
                conn.execute(text(f"ALTER TABLE strategy ADD COLUMN {col} {ddl}"))
                print(f"  [OK] added column '{col}'")

    print("\n[verify] strategy 当前字段:")
    insp = inspect(engine)
    new = {c for c, _ in COLS}
    for c in insp.get_columns("strategy"):
        marker = "  <NEW>" if c["name"] in new else ""
        print(f"  {c['name']:20} {str(c['type']):20} nullable={c['nullable']}{marker}")

    engine.dispose()
    print("\n[DONE] migration 完成")


if __name__ == "__main__":
    main()
