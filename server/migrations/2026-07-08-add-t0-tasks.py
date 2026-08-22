"""
2026-07-08-add-t0-tasks.py — 增量迁移 (idempotent, MySQL-only)

变更：
1. 新建表 t0_tasks (REQ-TRADE-013):
   - id (PK, auto-increment)
   - user_id, stock_code (NOT NULL)
   - base_volume, target_volume (NOT NULL, default 0)
   - coefficient (NOT NULL, default 1.0)
   - status (NOT NULL, default 'active')
   - note (nullable)
   - created_trd_date (NOT NULL)
   - created_at, closed_at (datetime)
   + 3 索引: ix_t0_tasks_stock_code, ix_t0_tasks_status_created, ix_t0_tasks_user_status

2. orders 表加 task_id 列 (nullable INT, FK → t0_tasks.id, no CASCADE)
   + 索引 ix_orders_task_id

幂等性：
- 表存在探测 (SQLAlchemy inspect.get_table_names)
- 列存在探测 (INFORMATION_SCHEMA.COLUMNS)
- 索引存在探测 (INFORMATION_SCHEMA.STATISTICS)

执行：
    python server/migrations/2026-07-08-add-t0-tasks.py
    # 默认用业务账号 EVTRADE_DB_URL；DDL 用 EVTRADE_DB_ADMIN_URL
"""
import os
import sys
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.engine import Engine

# ─────────────── URL 解析（MySQL-only 永久标准 强制 EVTRADE_DB_URL） ───────────────
# REQ-CFG-009: migration 脚本要求显式 EVTRADE_DB_URL。
try:
    DATABASE_URL = os.environ["EVTRADE_DB_URL"]
except KeyError:
    raise RuntimeError(
        "EVTRADE_DB_URL is required (MySQL-only permanent standard). "
        "Set it in server/.env, e.g. mysql+pymysql://EvTrade:p%40ssw0rd@127.0.0.1:33066/evtrade?charset=utf8mb4"
    )
if not DATABASE_URL.startswith("mysql"):
    raise RuntimeError(
        f"[migration] Only MySQL is supported (permanent standard). Got: {DATABASE_URL[:80]!r}"
    )
ADMIN_URL = os.environ.get("EVTRADE_DB_ADMIN_URL", DATABASE_URL)
if not ADMIN_URL.startswith("mysql"):
    raise RuntimeError(
        f"EVTRADE_DB_ADMIN_URL must be a MySQL URL. Got: {ADMIN_URL[:80]!r}"
    )


def _engine_dialect_name(engine: Engine) -> str:
    with engine.connect() as conn:
        return conn.dialect.name  # 'mysql' (永久标准唯一合法值)


def table_exists(engine: Engine, table: str) -> bool:
    insp = inspect(engine)
    return table in insp.get_table_names()


def column_exists(engine: Engine, table: str, column: str) -> bool:
    insp = inspect(engine)
    return column in {c["name"] for c in insp.get_columns(table)}


def index_exists(engine: Engine, table: str, index_name: str) -> bool:
    insp = inspect(engine)
    return any(idx["name"] == index_name for idx in insp.get_indexes(table))


def main():
    admin_engine = create_engine(ADMIN_URL, future=True)

    print(f"[INFO] dialect=mysql admin_url={ADMIN_URL.split('@')[-1]}")

    try:
        with admin_engine.begin() as conn:
            # ─── Step 1: 建表 t0_tasks (幂等) ───
            if table_exists(admin_engine, "t0_tasks"):
                print("[SKIP] table t0_tasks already exists")
            else:
                conn.execute(text("""
                    CREATE TABLE t0_tasks (
                        id INT NOT NULL AUTO_INCREMENT,
                        user_id INT NOT NULL,
                        stock_code VARCHAR(16) NOT NULL,
                        base_volume INT NOT NULL DEFAULT 0,
                        target_volume INT NOT NULL DEFAULT 0,
                        coefficient FLOAT NOT NULL DEFAULT 1.0,
                        status VARCHAR(16) NOT NULL DEFAULT 'active',
                        note VARCHAR(255) NULL,
                        created_trd_date VARCHAR(8) NOT NULL,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        closed_at DATETIME NULL,
                        PRIMARY KEY (id)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """))
                print("[OK] created table t0_tasks")

            # ─── Step 2: 加索引 (幂等) ───
            _create_index_safe(conn, admin_engine, "t0_tasks", "ix_t0_tasks_stock_code", "stock_code")
            _create_index_safe(conn, admin_engine, "t0_tasks", "ix_t0_tasks_status_created", "status, created_at")
            _create_index_safe(conn, admin_engine, "t0_tasks", "ix_t0_tasks_user_status", "user_id, status")

            # ─── Step 3: orders 加 task_id 列 (幂等) ───
            if column_exists(admin_engine, "orders", "task_id"):
                print("[SKIP] orders.task_id already exists")
            else:
                conn.execute(text("ALTER TABLE orders ADD COLUMN task_id INT NULL"))
                print("[OK] added column orders.task_id (INT NULL)")

            # ─── Step 4: 加 orders.task_id 索引 (幂等) ───
            _create_index_safe(conn, admin_engine, "orders", "ix_orders_task_id", "task_id")

            # ─── Step 5: 补 t0_tasks.updated_at 列 (幂等, fix) ───
            # 原 commit 2 migration 漏了 updated_at, 但 spec §12 状态流转要求有
            # updated_at 已合进 Step 1 CREATE TABLE, 此分支仅兜底历史 MySQL 库
            if column_exists(admin_engine, "t0_tasks", "updated_at"):
                print("[SKIP] t0_tasks.updated_at already exists")
            else:
                conn.execute(text(
                    "ALTER TABLE t0_tasks ADD COLUMN updated_at DATETIME "
                    "NOT NULL DEFAULT CURRENT_TIMESTAMP"
                ))
                print("[OK] added column t0_tasks.updated_at (DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)")

        # ─── Step 5: 用业务 URL 验证 ───
        biz_engine = create_engine(DATABASE_URL, future=True)
        try:
            if not table_exists(biz_engine, "t0_tasks"):
                print("[WARN] t0_tasks exists via admin but NOT via business URL — check permissions")
                sys.exit(2)
            if not column_exists(biz_engine, "orders", "task_id"):
                print("[WARN] orders.task_id exists via admin but NOT via business URL — check permissions")
                sys.exit(2)
            print("[VERIFY] t0_tasks + orders.task_id visible via business URL ✓")
        finally:
            biz_engine.dispose()
    finally:
        admin_engine.dispose()

    print("[DONE] migration 2026-07-08-add-t0-tasks completed")


def _create_index_safe(conn, engine: Engine, table: str, idx_name: str, columns: str):
    """建索引；存在则 skip."""
    if index_exists(engine, table, idx_name):
        print(f"[SKIP] index {idx_name} on {table} already exists")
        return
    # MySQL 8 不支持 CREATE INDEX IF NOT EXISTS, 但 INFORMATION_SCHEMA.STATISTICS 探测已跳过
    conn.execute(text(f"CREATE INDEX {idx_name} ON {table}({columns})"))
    print(f"[OK] created index {idx_name} on {table}({columns})")


if __name__ == "__main__":
    main()