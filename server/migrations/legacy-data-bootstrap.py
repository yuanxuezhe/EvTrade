"""
sqlite-to-mysql-migrate.py — 一次性 SQLite → MySQL 数据导入（REQ-CFG-009 migration 工具）

行为：
- 读源 SQLite (server/evtrade.db) 所有 user 表
- INSERT IGNORE 到目标 MySQL (EVTRADE_DB_URL)
- 业务账号权限足够（仅 SELECT + INSERT）；DDL 已由 init_db 准备
- 幂等：基于 PRIMARY KEY 自动去重
- 不动 schema（schema 走 init_db + migrations/*.py）

用法：
    # 1. 先在 MySQL 端跑 init_db 建表（已执行）
    # 2. 再导入数据
    python server/migrations/sqlite-to-mysql-migrate.py [SQLITE_PATH]

默认源：server/evtrade.db
"""
import os
import sys
import sqlite3
import pymysql
from sqlalchemy import create_engine, inspect

SRC_DEFAULT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "evtrade.db")
DST_URL = os.environ.get("EVTRADE_DB_URL", "sqlite:///./evtrade.db")


def list_user_tables(sq_conn: sqlite3.Connection) -> list[str]:
    """列 SQLite 所有 user 表（排除 sqlite_* 内部表）。"""
    rows = sq_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [r[0] for r in rows]


def get_create_table_sql(sq_conn: sqlite3.Connection, table: str) -> str:
    """取 SQLite 的 CREATE TABLE DDL（用于兼容参照）。"""
    row = sq_conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row[0] if row else ""


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else SRC_DEFAULT
    if not os.path.exists(src):
        print(f"[ERROR] SQLite 源不存在: {src}")
        sys.exit(1)

    # 解析 DSN → host/port/user/pass/db
    # 简单解析：mysql+pymysql://USER:PASS@HOST:PORT/DB?charset=utf8mb4
    if not DST_URL.startswith("mysql"):
        print(f"[ERROR] 当前 EVTRADE_DB_URL 不是 mysql: {DST_URL}")
        sys.exit(1)
    from urllib.parse import urlparse, unquote
    u = urlparse(DST_URL.replace("mysql+pymysql://", "mysql://"))
    host = u.hostname or "127.0.0.1"
    port = u.port or 3306
    user = unquote(u.username or "")
    pw = unquote(u.password or "")
    db = (u.path or "/").lstrip("/").split("?")[0]

    print(f"[SRC] sqlite={src}")
    print(f"[DST] mysql={user}@{host}:{port}/{db}")

    sq = sqlite3.connect(src)
    sq.row_factory = sqlite3.Row
    tables = list_user_tables(sq)
    print(f"[INFO] SQLite user tables: {len(tables)}")

    my = pymysql.connect(host=host, port=port, user=user, password=pw, database=db, autocommit=False)
    my_cur = my.cursor()
    insp = create_engine(DST_URL)
    sql_inspector = inspect(insp)

    total_rows = 0
    for t in tables:
        # 取 MySQL 端列（用 sqlalchemy inspect）
        try:
            my_cols = [c['name'] for c in sql_inspector.get_columns(t)]
        except Exception as e:
            print(f"  [{t}] SKIP — MySQL 表不存在 ({e})")
            continue
        if not my_cols:
            print(f"  [{t}] SKIP — MySQL 表无列")
            continue

        rows = sq.execute(f"SELECT * FROM {t}").fetchall()
        if not rows:
            print(f"  [{t}] 0 rows (empty)")
            continue

        # 按 MySQL 列序取行字段
        sq_cols = rows[0].keys()
        common_cols = [c for c in my_cols if c in sq_cols]
        if not common_cols:
            print(f"  [{t}] SKIP — 无公共列")
            continue
        my_only_cols = [c for c in my_cols if c not in sq_cols]

        # INSERT IGNORE 防主键冲突
        placeholders = ", ".join(["%s"] * len(common_cols))
        col_list = ", ".join(f"`{c}`" for c in common_cols)
        sql = f"INSERT IGNORE INTO `{t}` ({col_list}) VALUES ({placeholders})"

        n_inserted = 0
        for row in rows:
            vals = [row[c] for c in common_cols]
            try:
                my_cur.execute(sql, vals)
                n_inserted += my_cur.rowcount
            except Exception as e:
                print(f"    [{t}] row error: {e}")
                my.rollback()
                break
        my.commit()
        total_rows += n_inserted
        extra = f" (mysql-only cols default: {my_only_cols})" if my_only_cols else ""
        print(f"  [{t}] {len(rows)} source → {n_inserted} inserted{extra}")

    sq.close()
    my.close()
    insp.dispose()
    print(f"\n[OK] total rows inserted: {total_rows}")


if __name__ == "__main__":
    main()