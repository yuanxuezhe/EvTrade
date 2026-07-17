"""
2026-07-17-add-orders-strategy-type.py — v66 增量迁移 (idempotent, MySQL-only v20)

变更 (REQ-TRADE-026):
1. orders 表加 strategy_type 列 (TINYINT NOT NULL DEFAULT 0)
   - 0 = 普通单 (Trade.vue OrderForm 下单)
   - 1 = 快速做T (T0Trade.vue useT0OrderSubmit.submitOrder 下单)
   - 默认 0: 历史 user_def='' 单全部视为普通单 (向后兼容, 不回填)

2. 加索引 ix_orders_strategy_type(strategy_type)
   - 供缓存过滤 (T0Trade 委托明细 filter strategy_type=1)
   - 供未来策略维度报表聚合

幂等性:
- 列存在探测 (INFORMATION_SCHEMA.COLUMNS via SQLAlchemy inspect)
- 索引存在探测 (INFORMATION_SCHEMA.STATISTICS via SQLAlchemy inspect)

执行:
    python server/migrations/2026-07-17-add-orders-strategy-type.py
    # 默认用业务账号 EVTRADE_DB_URL；DDL 用 EVTRADE_DB_ADMIN_URL
"""
import os
import sys
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
        f"[migration] EVTRADE_DB_ADMIN_URL must be a MySQL URL. Got: {ADMIN_URL[:80]!r}"
    )


def _engine_dialect_name(engine: Engine) -> str:
    with engine.connect() as conn:
        return conn.dialect.name  # 'mysql' (v20 永久标准唯一合法值)


def column_exists(engine: Engine, table: str, column: str) -> bool:
    insp = inspect(engine)
    return column in {c["name"] for c in insp.get_columns(table)}


def index_exists(engine: Engine, table: str, index_name: str) -> bool:
    insp = inspect(engine)
    return any(idx["name"] == index_name for idx in insp.get_indexes(table))


def _create_index_safe(conn, engine: Engine, table: str, idx_name: str, columns: str):
    """建索引；存在则 skip."""
    if index_exists(engine, table, idx_name):
        print(f"[SKIP] index {idx_name} on {table} already exists")
        return
    # MySQL 8 不支持 CREATE INDEX IF NOT EXISTS, 但 INFORMATION_SCHEMA.STATISTICS 探测已跳过
    conn.execute(text(f"CREATE INDEX {idx_name} ON {table}({columns})"))
    print(f"[OK] created index {idx_name} on {table}({columns})")


def main():
    admin_engine = create_engine(ADMIN_URL, future=True)

    print(f"[INFO] dialect=mysql admin_url={ADMIN_URL.split('@')[-1]}")

    try:
        with admin_engine.begin() as conn:
            # ─── Step 1: orders 加 strategy_type 列 (幂等) ───
            if column_exists(admin_engine, "orders", "strategy_type"):
                print("[SKIP] orders.strategy_type already exists")
            else:
                # v66: TINYINT NOT NULL DEFAULT 0
                #   MySQL 8 ALGORITHM=INPLACE 不重写表 (默认 0 不需 rewrite)
                #   0 = 普通单, 1 = 快速做T, 未来扩展可改 SMALLINT
                conn.execute(text(
                    "ALTER TABLE orders ADD COLUMN strategy_type TINYINT NOT NULL DEFAULT 0"
                ))
                print("[OK] added column orders.strategy_type (TINYINT NOT NULL DEFAULT 0)")

            # ─── Step 2: 加 orders.strategy_type 索引 (幂等) ───
            _create_index_safe(conn, admin_engine, "orders", "ix_orders_strategy_type", "strategy_type")

        # ─── Step 3: 用业务 URL 验证 (确保业务账号有读权限) ───
        biz_engine = create_engine(DATABASE_URL, future=True)
        try:
            if not column_exists(biz_engine, "orders", "strategy_type"):
                print("[WARN] orders.strategy_type exists via admin but NOT via business URL — check permissions")
                sys.exit(2)
            if not index_exists(biz_engine, "orders", "ix_orders_strategy_type"):
                print("[WARN] ix_orders_strategy_type exists via admin but NOT via business URL — check permissions")
                sys.exit(2)
            print("[VERIFY] orders.strategy_type + ix_orders_strategy_type visible via business URL ✓")
        finally:
            biz_engine.dispose()
    finally:
        admin_engine.dispose()

    print("[DONE] migration 2026-07-17-add-orders-strategy-type completed")


if __name__ == "__main__":
    main()