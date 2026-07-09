"""
2026-07-09-add-quote-snapshots-unique.py — quote_snapshot-subscribe 增量迁移

变更：
1. 给 quote_snapshots.stock_code 加 UNIQUE 约束（latest-only 模型：每 stock_code 1 行）
   - SQLite: CREATE UNIQUE INDEX uq_quote_snapshots_stock_code ON quote_snapshots(stock_code)
   - MySQL : ALTER TABLE quote_snapshots ADD UNIQUE KEY uq_quote_snapshots_stock_code (stock_code)
2. 注：QuoteSnapshot ORM 已同步加 UniqueConstraint("stock_code", name="uq_quote_snapshots_stock_code")
   (server/models/orm.py:301-303)，新建库 init_db 会自动建。

幂等性：
- 索引/约束存在探测（INFORMATION_SCHEMA.STATISTICS / sqlite_master）
- 已存在则 skip

执行：
    python server/migrations/2026-07-09-add-quote-snapshots-unique.py
    # 默认用业务账号 EVTRADE_DB_URL；DDL 用 EVTRADE_DB_ADMIN_URL
"""
import os
import sys
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.engine import Engine

# ─────────────── URL 解析（同 2026-07-08 migration） ───────────────
DEFAULT_URL = "sqlite:///./evtrade.db"
DATABASE_URL = os.environ.get("EVTRADE_DB_URL", DEFAULT_URL)
# ALTER TABLE 需要 DDL；优先 ADMIN_URL，回退业务 URL
ADMIN_URL = os.environ.get("EVTRADE_DB_ADMIN_URL", DATABASE_URL)

IDX_NAME = "uq_quote_snapshots_stock_code"
TABLE_NAME = "quote_snapshots"


def _engine_dialect_name(engine: Engine) -> str:
    with engine.connect() as conn:
        return conn.dialect.name  # 'mysql' / 'sqlite' / ...


def table_exists(engine: Engine, table: str) -> bool:
    insp = inspect(engine)
    return table in insp.get_table_names()


def index_exists(engine: Engine, table: str, index_name: str) -> bool:
    insp = inspect(engine)
    return any(idx["name"] == index_name for idx in insp.get_indexes(table))


def main():
    admin_engine = create_engine(ADMIN_URL, future=True)
    dialect = _engine_dialect_name(admin_engine)
    is_mysql = dialect == "mysql"

    print(f"[INFO] dialect={dialect} admin_url={ADMIN_URL.split('@')[-1]}")

    try:
        with admin_engine.begin() as conn:
            # ─── Step 1: 表存在探测 ───
            if not table_exists(admin_engine, TABLE_NAME):
                print(f"[SKIP] table {TABLE_NAME} 不存在，待 init_db 建表后会自动带 UniqueConstraint")
                return

            # ─── Step 2: 已存在探测 ───
            if index_exists(admin_engine, TABLE_NAME, IDX_NAME):
                print(f"[SKIP] {IDX_NAME} on {TABLE_NAME} already exists")
                return

            # ─── Step 3: 建唯一索引 ───
            if is_mysql:
                # MySQL 8 同样不支持 CREATE UNIQUE INDEX IF NOT EXISTS，但前面已探测
                conn.execute(text(
                    f"CREATE UNIQUE INDEX {IDX_NAME} ON {TABLE_NAME}(stock_code)"
                ))
            else:
                # SQLite 同样
                conn.execute(text(
                    f"CREATE UNIQUE INDEX {IDX_NAME} ON {TABLE_NAME}(stock_code)"
                ))
            print(f"[OK] created unique index {IDX_NAME} on {TABLE_NAME}(stock_code)")

        # ─── Step 4: 用业务 URL 验证可见 ───
        biz_engine = create_engine(DATABASE_URL, future=True)
        try:
            if not index_exists(biz_engine, TABLE_NAME, IDX_NAME):
                print(f"[WARN] {IDX_NAME} exists via admin but NOT via business URL — check permissions")
                sys.exit(2)
            print(f"[VERIFY] {IDX_NAME} visible via business URL ✓")
        finally:
            biz_engine.dispose()
    finally:
        admin_engine.dispose()

    print("[DONE] migration 2026-07-09-add-quote-snapshots-unique completed")


if __name__ == "__main__":
    main()