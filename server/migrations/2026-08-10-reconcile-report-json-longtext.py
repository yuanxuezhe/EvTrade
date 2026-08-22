"""
2026-08-10-reconcile-report-json-longtext.py — DB 迁移: reconcile_report JSON 列 TEXT→LONGTEXT

修复手动日初 init 返回 500:
  pymysql.err.DataError: (1406, "Data too long for column 'local_positions_json' at row 1")

do_reconcile(reconcile_kind='init') 把本地全量持仓快照 (2197 只 ≈ 数百 KB JSON) 写入
reconcile_report.local_positions_json。历史 DB 列容量不足 → 溢出。
orm.py / schema.yml 已声明 LONGTEXT, 本迁移仅对齐 DB 实际列。

实际 DB 前态存在两处漂移:
  evtrade_dev: varchar(255)  (比 TEXT 更小, 之前守卫 REFUSE 拒绝处理 → init 仍 500)
  evtrade:     text          (上限 64KB, 亦不足)

涉及 5 列:
  diffs_json / broker_asset_json / local_asset_json / broker_positions_json / local_positions_json

幂等: 仅当列当前为 varchar/char/text/mediumtext (非 longtext) 时 MODIFY; 已是 longtext 则跳过。

执行:
    python3 server/migrations/2026-08-10-reconcile-report-json-longtext.py
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

from sqlalchemy import text, create_engine, inspect

DATABASE_URL = os.environ.get("EVTRADE_DB_URL")
if not DATABASE_URL:
    raise RuntimeError("EVTRADE_DB_URL is required (MySQL-only permanent standard).")
if not DATABASE_URL.startswith("mysql"):
    raise RuntimeError(f"Only MySQL is supported. Got URL: {DATABASE_URL[:80]!r}")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

TABLE = "reconcile_report"
# 5 个 JSON 快照列: 统一 LONGTEXT (对齐 orm.py / schema.yml / tables codegen)
JSON_COLUMNS = [
    "diffs_json",
    "broker_asset_json",
    "local_asset_json",
    "broker_positions_json",
    "local_positions_json",
]


def _column_type(conn, table: str, column: str) -> str | None:
    """返回列当前 MySQL 数据类型 (如 'text' / 'longtext'), 无列则 None"""
    row = conn.execute(
        text("""
            SELECT DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE()
               AND TABLE_NAME = :t
               AND COLUMN_NAME = :c
             LIMIT 1
        """),
        {"t": table, "c": column},
    ).first()
    return row[0] if row else None


def main() -> None:
    print("[start] reconcile_report JSON columns -> LONGTEXT")
    print(f"  db: {DATABASE_URL.split('@')[-1] if DATABASE_URL else 'NONE'}")
    print(f"  table: {TABLE}, columns: {JSON_COLUMNS}")

    with engine.begin() as conn:
        for col in JSON_COLUMNS:
            cur = _column_type(conn, TABLE, col)
            if cur is None:
                print(f"  [skip] column '{col}' not exists")
                continue
            if cur == "longtext":
                print(f"  [skip] '{col}' already longtext")
                continue
            if cur not in ("text", "mediumtext", "varchar", "char"):
                print(f"  [REFUSE] '{col}' current type '{cur}', expected varchar/char/text/mediumtext. 请人工确认后再改!")
                continue
            conn.execute(text(
                f"ALTER TABLE `{TABLE}` MODIFY `{col}` LONGTEXT"
            ))
            print(f"  [OK] '{col}' {cur} -> longtext")

    # ──── 验证 ────
    print("\n[verify] reconcile_report 当前字段:")
    insp = inspect(engine)
    for c in insp.get_columns(TABLE):
        marker = "  <LONGTEXT>" if c["name"] in JSON_COLUMNS else ""
        print(f"  {c['name']:25} {str(c['type']):20} nullable={c['nullable']}{marker}")

    engine.dispose()
    print("\n[DONE] migration 完成")
    print("  验证: 手动重试 POST /api/admin/sys-status/init 应返回 200, 不再 500")


if __name__ == "__main__":
    main()
