"""
2026-07-09-add-quote-snapshots-unique.py — quote_snapshot-subscribe 增量迁移

变更：
1. 给 quote_snapshots.stock_code 加 UNIQUE 约束（latest-only 模型：每 stock_code 1 行）
   - MySQL : CREATE UNIQUE INDEX uq_quote_snapshots_stock_code ON quote_snapshots(stock_code)
2. 注：QuoteSnapshot ORM 已同步加 UniqueConstraint("stock_code", name="uq_quote_snapshots_stock_code")
   (server/models/orm.py:301-303)，新建库 init_db 会自动建。

幂等性：
- 索引/约束存在探测（INFORMATION_SCHEMA.STATISTICS）
- 已存在则 skip

执行：
    python server/migrations/2026-07-09-add-quote-snapshots-unique.py
    # 默认用业务账号 EVTRADE_DB_URL；DDL 用 EVTRADE_DB_ADMIN_URL
"""
import os
import sys
# 2026-07-10 fix: migration 脚本直接读 os.environ，与 infra/db.py 同问题
# 这里也 load_dotenv(server/.env) 拿到正确的 EVTRADE_DB_URL。
try:
    from dotenv import load_dotenv
    _ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
    if os.path.exists(_ENV_PATH):
        load_dotenv(_ENV_PATH, override=False)
except ImportError:
    pass
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.engine import Engine

# ─────────────── URL 解析（v20 MySQL-only 永久标准 强制 EVTRADE_DB_URL） ───────────────
# REQ-CFG-009 v20: SQLite fallback 永久下线；migration 脚本同样要求显式 EVTRADE_DB_URL。
try:
    DATABASE_URL = os.environ["EVTRADE_DB_URL"]
except KeyError:
    raise RuntimeError(
        "EVTRADE_DB_URL is required (v20 MySQL-only permanent standard). "
        "Set it in server/.env, e.g. mysql+pymysql://EvTrade:p%40ssw0rd@127.0.0.1:33066/evtrade?charset=utf8mb4"
    )
if not DATABASE_URL.startswith("mysql"):
    raise RuntimeError(
        f"[migration] Only MySQL is supported (v20 permanent standard). Got: {DATABASE_URL[:80]!r}"
    )
ADMIN_URL = os.environ.get("EVTRADE_DB_ADMIN_URL", DATABASE_URL)
if not ADMIN_URL.startswith("mysql"):
    raise RuntimeError(
        f"EVTRADE_DB_ADMIN_URL must be a MySQL URL. Got: {ADMIN_URL[:80]!r}"
    )


IDX_NAME = "uq_quote_snapshots_stock_code"
TABLE_NAME = "quote_snapshots"


def _engine_dialect_name(engine: Engine) -> str:
    with engine.connect() as conn:
        return conn.dialect.name  # 'mysql' (v20 永久标准唯一合法值)


def table_exists(engine: Engine, table: str) -> bool:
    insp = inspect(engine)
    return table in insp.get_table_names()


def index_exists(engine: Engine, table: str, index_name: str) -> bool:
    insp = inspect(engine)
    return any(idx["name"] == index_name for idx in insp.get_indexes(table))


def main():
    admin_engine = create_engine(ADMIN_URL, future=True)

    print(f"[INFO] dialect=mysql admin_url={ADMIN_URL.split('@')[-1]}")

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

            # ─── Step 3: 建唯一索引（v20 MySQL-only） ───
            # MySQL 8 不支持 CREATE UNIQUE INDEX IF NOT EXISTS，但 INFORMATION_SCHEMA 已探测过
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