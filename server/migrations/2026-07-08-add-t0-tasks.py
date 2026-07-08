"""
2026-07-08-add-t0-tasks.py — v18 增量迁移 (idempotent, SQLAlchemy 双 driver)

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
- 列存在探测 (INFORMATION_SCHEMA.COLUMNS / PRAGMA table_info)
- 索引存在探测 (INFORMATION_SCHEMA.STATISTICS / sqlite_master)

执行：
    python server/migrations/2026-07-08-add-t0-tasks.py
    # 默认用业务账号 EVTRADE_DB_URL；DDL 用 EVTRADE_DB_ADMIN_URL
"""
import os
import sys
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.engine import Engine

# ─────────────── URL 解析（同 infra/db.py） ───────────────
DEFAULT_URL = "sqlite:///./evtrade.db"
DATABASE_URL = os.environ.get("EVTRADE_DB_URL", DEFAULT_URL)
# ALTER TABLE 需要 DDL；优先 ADMIN_URL，回退业务 URL
ADMIN_URL = os.environ.get("EVTRADE_DB_ADMIN_URL", DATABASE_URL)


def _engine_dialect_name(engine: Engine) -> str:
    with engine.connect() as conn:
        return conn.dialect.name  # 'mysql' / 'sqlite' / ...


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
    dialect = _engine_dialect_name(admin_engine)
    is_mysql = dialect == "mysql"

    print(f"[INFO] dialect={dialect} admin_url={ADMIN_URL.split('@')[-1]}")

    try:
        with admin_engine.begin() as conn:
            # ─── Step 1: 建表 t0_tasks (幂等) ───
            if table_exists(admin_engine, "t0_tasks"):
                print("[SKIP] table t0_tasks already exists")
            else:
                if is_mysql:
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
                            closed_at DATETIME NULL,
                            PRIMARY KEY (id)
                        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                    """))
                else:
                    # SQLite
                    conn.execute(text("""
                        CREATE TABLE t0_tasks (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            user_id INTEGER NOT NULL,
                            stock_code VARCHAR(16) NOT NULL,
                            base_volume INTEGER NOT NULL DEFAULT 0,
                            target_volume INTEGER NOT NULL DEFAULT 0,
                            coefficient REAL NOT NULL DEFAULT 1.0,
                            status VARCHAR(16) NOT NULL DEFAULT 'active',
                            note VARCHAR(255) NULL,
                            created_trd_date VARCHAR(8) NOT NULL,
                            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            closed_at DATETIME NULL
                        )
                    """))
                print("[OK] created table t0_tasks")

            # ─── Step 2: 加索引 (幂等) ───
            _create_index_safe(conn, admin_engine, is_mysql, "t0_tasks", "ix_t0_tasks_stock_code", "stock_code")
            _create_index_safe(conn, admin_engine, is_mysql, "t0_tasks", "ix_t0_tasks_status_created", "status, created_at")
            _create_index_safe(conn, admin_engine, is_mysql, "t0_tasks", "ix_t0_tasks_user_status", "user_id, status")

            # ─── Step 3: orders 加 task_id 列 (幂等) ───
            if column_exists(admin_engine, "orders", "task_id"):
                print("[SKIP] orders.task_id already exists")
            else:
                if is_mysql:
                    conn.execute(text("ALTER TABLE orders ADD COLUMN task_id INT NULL"))
                else:
                    conn.execute(text("ALTER TABLE orders ADD COLUMN task_id INTEGER"))
                print("[OK] added column orders.task_id (INT NULL)")

            # ─── Step 4: 加 orders.task_id 索引 (幂等) ───
            _create_index_safe(conn, admin_engine, is_mysql, "orders", "ix_orders_task_id", "task_id")

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


def _create_index_safe(conn, engine: Engine, is_mysql: bool, table: str, idx_name: str, columns: str):
    """建索引；存在则 skip。"""
    if index_exists(engine, table, idx_name):
        print(f"[SKIP] index {idx_name} on {table} already exists")
        return
    if is_mysql:
        # MySQL 8 不支持 CREATE INDEX IF NOT EXISTS, 但 INFORMATION_SCHEMA.STATISTICS 探测已跳过
        conn.execute(text(f"CREATE INDEX {idx_name} ON {table}({columns})"))
    else:
        # SQLite 同理
        conn.execute(text(f"CREATE INDEX {idx_name} ON {table}({columns})"))
    print(f"[OK] created index {idx_name} on {table}({columns})")


if __name__ == "__main__":
    main()