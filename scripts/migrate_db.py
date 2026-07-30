"""
migrate_db.py — Copy data from evtrade → evtrade_dev using raw pymysql.

Usage:
    uv run python scripts/migrate_db.py
"""
import pymysql

SRC = {"host": "192.168.10.2", "port": 33066, "user": "EvTrade", "password": "p@ssw0rd", "database": "evtrade", "charset": "utf8mb4"}
DST = {"host": "192.168.10.2", "port": 33066, "user": "EvTrade", "password": "p@ssw0rd", "database": "evtrade_dev", "charset": "utf8mb4"}

src = pymysql.connect(**SRC)
dst = pymysql.connect(**DST)

# Safety check
cur = dst.cursor()
cur.execute("SELECT DATABASE()")
assert cur.fetchone()[0] == "evtrade_dev", "ABORT: wrong target DB"

# Get source tables
src_cur = src.cursor()
src_cur.execute("SHOW TABLES")
tables = [r[0] for r in src_cur.fetchall()]
print(f"Source tables ({len(tables)}): {tables}")

# Tables that need INSERT ... ON DUPLICATE KEY UPDATE (have unique constraints and may have live data)
UPSERT_TABLES = {"quote_snapshots"}

for tbl in tables:
    print(f"\n=== {tbl} ===")

    src_cur.execute(f"SELECT * FROM `{tbl}`")
    rows = src_cur.fetchall()
    columns = [desc[0] for desc in src_cur.description]

    if not rows:
        print("  (empty)")
        continue

    cur.execute("SET FOREIGN_KEY_CHECKS=0")

    if tbl in UPSERT_TABLES:
        # Find the unique key columns for upsert
        src_cur.execute(f"SHOW INDEX FROM `{tbl}` WHERE Non_unique = 0")
        idx_cols = [r[4] for r in src_cur.fetchall()]
        # Build ON DUPLICATE KEY UPDATE clause
        updatable = [c for c in columns if c not in idx_cols]
        update_clause = ", ".join([f"`{c}` = VALUES(`{c}`)" for c in updatable])
        placeholders = ", ".join(["%s"] * len(columns))
        col_str = ", ".join([f"`{c}`" for c in columns])
        sql = f"INSERT INTO `{tbl}` ({col_str}) VALUES ({placeholders}) ON DUPLICATE KEY UPDATE {update_clause}"
    else:
        cur.execute(f"TRUNCATE TABLE `{tbl}`")
        placeholders = ", ".join(["%s"] * len(columns))
        col_str = ", ".join([f"`{c}`" for c in columns])
        sql = f"INSERT INTO `{tbl}` ({col_str}) VALUES ({placeholders})"

    cur.executemany(sql, rows)
    print(f"  inserted {len(rows)} rows")

cur.execute("SET FOREIGN_KEY_CHECKS=1")
dst.commit()

print("\nDone. Verifying target...")
cur.execute("USE evtrade_dev")
for tbl in tables:
    cur.execute(f"SELECT COUNT(*) FROM `{tbl}`")
    print(f"  {tbl}: {cur.fetchone()[0]} rows")

src.close()
dst.close()
