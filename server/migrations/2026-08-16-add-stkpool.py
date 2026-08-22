"""
2026-08-16-add-stkpool.py — DB 迁移 (add-stkpool-module change)

3 步幂等迁移:
1. CREATE TABLE stkpool (主表: id 自增, name 唯一, remark, created_at)
2. CREATE TABLE stkpooldetail (明细: 复合 PK (id, stock_code), FK ON DELETE CASCADE)
3. ALTER TABLE stkpool ADD UNIQUE KEY uk_stkpool_name (name) (CREATE 阶段已含 UK, 幂等探测)

幂等: INFORMATION_SCHEMA 探测 + CREATE TABLE IF NOT EXISTS。

执行:
    python3 server/migrations/2026-08-16-add-stkpool.py
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
    raise RuntimeError(f"Only MySQL is supported (permanent standard). Got URL: {DATABASE_URL[:80]!r}")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)


def _table_exists(conn, table: str) -> bool:
    row = conn.execute(
        text("""
            SELECT 1 FROM INFORMATION_SCHEMA.TABLES
             WHERE TABLE_SCHEMA = DATABASE()
               AND TABLE_NAME = :t
             LIMIT 1
        """),
        {"t": table},
    ).first()
    return row is not None


def _index_exists(conn, table: str, index: str) -> bool:
    row = conn.execute(
        text("""
            SELECT 1 FROM INFORMATION_SCHEMA.STATISTICS
             WHERE TABLE_SCHEMA = DATABASE()
               AND TABLE_NAME = :t
               AND INDEX_NAME = :i
             LIMIT 1
        """),
        {"t": table, "i": index},
    ).first()
    return row is not None


def create_stkpool_table(conn) -> None:
    """建 stkpool 主表 (幂等: 已存在跳过)."""
    if _table_exists(conn, "stkpool"):
        print("  [skip] table 'stkpool' already exists")
        return

    conn.execute(text("""
        CREATE TABLE stkpool (
            id INT NOT NULL AUTO_INCREMENT COMMENT '行主键',
            name VARCHAR(64) NOT NULL COMMENT '池名 (唯一)',
            remark VARCHAR(255) NOT NULL DEFAULT '' COMMENT '备注',
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
            PRIMARY KEY (id),
            UNIQUE KEY uk_stkpool_name (name)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        COMMENT='证券池主表'
    """))
    print("  [OK] created table 'stkpool'")


def create_stkpooldetail_table(conn) -> None:
    """建 stkpooldetail 明细表 (幂等: 已存在跳过)."""
    if _table_exists(conn, "stkpooldetail"):
        print("  [skip] table 'stkpooldetail' already exists")
        return

    conn.execute(text("""
        CREATE TABLE stkpooldetail (
            id INT NOT NULL COMMENT '共享主表 id (不自增, 与 stkpool.id 一一对应)',
            stock_code VARCHAR(16) NOT NULL COMMENT '股票代码',
            PRIMARY KEY (id, stock_code),
            KEY ix_stkpooldetail_id (id),
            FOREIGN KEY (id) REFERENCES stkpool(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        COMMENT='证券池明细: share PK id + stock_code'
    """))
    print("  [OK] created table 'stkpooldetail'")


def ensure_stkpool_unique_name(conn) -> None:
    """uk_stkpool_name (CREATE 阶段已含, 此处兜底探测)."""
    if _index_exists(conn, "stkpool", "uk_stkpool_name"):
        print("  [skip] index 'uk_stkpool_name' already exists")
        return
    # 兜底: CREATE 阶段已含 UK, 不会走到这里
    conn.execute(text("""
        ALTER TABLE stkpool ADD UNIQUE KEY uk_stkpool_name (name)
    """))
    print("  [OK] added index 'uk_stkpool_name'")


def main() -> None:
    print("[start] add stkpool module (证券池)")
    print(f"  db: {DATABASE_URL.split('@')[-1] if DATABASE_URL else 'NONE'}")

    with engine.begin() as conn:
        create_stkpool_table(conn)
        create_stkpooldetail_table(conn)
        ensure_stkpool_unique_name(conn)

    print("\n[verify] 关键对象存在性:")
    insp = inspect(engine)
    tables = insp.get_table_names()
    for required in ("stkpool", "stkpooldetail"):
        marker = "[OK]" if required in tables else "[MISS]"
        col_count = len(insp.get_columns(required)) if required in tables else 0
        print(f"  {marker} table '{required}' ({col_count} 列)")

    if "stkpool" in tables:
        idx = {i["name"] for i in insp.get_indexes("stkpool")}
        for required in ("PRIMARY", "uk_stkpool_name"):
            marker = "[OK]" if required in idx else "[MISS]"
            print(f"    {marker} index 'stkpool.{required}'")

    if "stkpooldetail" in tables:
        idx = {i["name"] for i in insp.get_indexes("stkpooldetail")}
        for required in ("PRIMARY", "ix_stkpooldetail_id"):
            marker = "[OK]" if required in idx else "[MISS]"
            print(f"    {marker} index 'stkpooldetail.{required}'")

        # FK 校验
        fks = insp.get_foreign_keys("stkpooldetail")
        cascade_ok = any(
            fk.get("referred_table") == "stkpool"
            and "CASCADE" in (fk.get("options", {}).get("ondelete") or "").upper()
            for fk in fks
        )
        print(f"    {'[OK]' if cascade_ok else '[MISS]'} FK stkpooldetail.id -> stkpool.id ON DELETE CASCADE")

    engine.dispose()
    print("\n[DONE] 证券池迁移完成")


if __name__ == "__main__":
    main()
