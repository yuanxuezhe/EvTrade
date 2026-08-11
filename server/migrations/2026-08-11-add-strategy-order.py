"""
2026-08-11-add-strategy-order.py — DB 迁移 (v126, 策略下单母单)

3 步幂等迁移:
1. CREATE TABLE strategy_order (母单, 7 列 + 3 索引)
2. INSERT IGNORE INTO order_no_seq 添加 strategy_order 生成器 (复用 v123 多生成器)
3. ALTER TABLE orders MODIFY strategy_type COMMENT 更新 (0=普通单 1=快速做T 2=策略下单)

幂等: INFORMATION_SCHEMA 探测 + INSERT IGNORE; 复跑 2 次不报错。
仿 2026-08-11-add-strategy-visibility.py (88 行) + 2026-08-11-order-no-seq-multi-generator.py 模板。

执行:
    python3 server/migrations/2026-08-11-add-strategy-order.py
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
    raise RuntimeError("EVTRADE_DB_URL is required (v20 MySQL-only permanent standard).")
if not DATABASE_URL.startswith("mysql"):
    raise RuntimeError(f"Only MySQL is supported (v20 permanent standard). Got URL: {DATABASE_URL[:80]!r}")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

# v126: 母单 task_id 与 order_no / task_batch 共用 order_no_seq 多生成器
# 撞号风险详见 openspec/changes/2026-08-11-strategy-order-design/proposal.md §风险 1 (用户决策: 不修)
SEED_LAST_VALUE = 10000000


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


def create_strategy_order_table(conn) -> None:
    """建 strategy_order 母单表 (幂等: 已存在跳过)."""
    if _table_exists(conn, "strategy_order"):
        print("  [skip] table 'strategy_order' already exists")
        return

    conn.execute(text("""
        CREATE TABLE strategy_order (
            id INT NOT NULL AUTO_INCREMENT COMMENT '行主键',
            task_id INT NOT NULL COMMENT '母单对外编号 (order_no_seq.strategy_order 生成器); 子单 orders.task_id 指向它',
            user_id INT NOT NULL COMMENT 'owner',
            strategy_id INT NOT NULL COMMENT '关联 strategy.strategy_id',
            stock_code VARCHAR(16) NOT NULL DEFAULT '' COMMENT '冗余自 strategy.stock_code (展示/过滤)',
            status VARCHAR(16) NOT NULL DEFAULT 'stopped' COMMENT 'stopped / running / closed',
            active_task_id INT NULL COMMENT '当前 live strategy_task.id (停止时转发 /internal/stop-task 用)',
            run_count INT NOT NULL DEFAULT 0 COMMENT '累计启动次数',
            last_started_at DATETIME NULL,
            last_stopped_at DATETIME NULL,
            closed_at DATETIME NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            UNIQUE KEY uk_strategy_order_task_id (task_id),
            KEY ix_strategy_order_user_id (user_id),
            KEY ix_strategy_order_strategy_id (strategy_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        COMMENT='v126 策略下单母单: 可重复启停, 子单按 parent_task_id 归因'
    """))
    print("  [OK] created table 'strategy_order'")


def ensure_strategy_order_generator(conn) -> None:
    """order_no_seq 插入 strategy_order 生成器 (INSERT IGNORE 幂等)."""
    res = conn.execute(
        text("""
            INSERT IGNORE INTO order_no_seq (`seq_name`, `last_value`, `updated_at`)
            VALUES ('strategy_order', :seed, CURRENT_TIMESTAMP)
        """),
        {"seed": SEED_LAST_VALUE},
    )
    if res.rowcount > 0:
        print(f"  [OK] inserted 'strategy_order' generator (seed={SEED_LAST_VALUE})")
    else:
        print("  [skip] 'strategy_order' generator already exists")


def update_orders_strategy_type_comment(conn) -> None:
    """ALTER orders.strategy_type COMMENT 更新 (COMMENT-only 幂等)."""
    if not _column_exists(conn, "orders", "strategy_type"):
        print("  [WARN] orders.strategy_type column not found, skip COMMENT update")
        return

    # INFORMATION_SCHEMA.COLUMNS.COLUMN_COMMENT 探测当前 COMMENT, 幂等
    row = conn.execute(
        text("""
            SELECT COLUMN_COMMENT FROM INFORMATION_SCHEMA.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE()
               AND TABLE_NAME = 'orders'
               AND COLUMN_NAME = 'strategy_type'
             LIMIT 1
        """),
    ).first()
    current_comment = (row[0] if row else "") or ""
    target_comment = "0=普通单 1=快速做T 2=策略下单"
    if target_comment in current_comment:
        print("  [skip] orders.strategy_type COMMENT already up-to-date")
        return

    # COMMENT-only ALTER (列类型 TINYINT 不变, 不影响数据)
    conn.execute(text("""
        ALTER TABLE orders MODIFY COLUMN strategy_type TINYINT NOT NULL DEFAULT 0
        COMMENT '0=普通单 1=快速做T 2=策略下单'
    """))
    print("  [OK] updated orders.strategy_type COMMENT to '0=普通单 1=快速做T 2=策略下单'")


def main() -> None:
    print("[start] add strategy order persistence (v126, 母单)")
    print(f"  db: {DATABASE_URL.split('@')[-1] if DATABASE_URL else 'NONE'}")

    with engine.begin() as conn:
        create_strategy_order_table(conn)
        ensure_strategy_order_generator(conn)
        update_orders_strategy_type_comment(conn)

    print("\n[verify] 关键对象存在性:")
    insp = inspect(engine)
    tables = insp.get_table_names()
    if "strategy_order" in tables:
        print(f"  [OK] table 'strategy_order' present ({len(insp.get_columns('strategy_order'))} 列)")
        idx = insp.get_indexes("strategy_order")
        idx_names = {i["name"] for i in idx}
        for required in ("uk_strategy_order_task_id", "ix_strategy_order_user_id", "ix_strategy_order_strategy_id"):
            marker = "[OK]" if required in idx_names else "[MISS]"
            print(f"    {marker} index '{required}'")
    else:
        print("  [MISS] table 'strategy_order' MISSING")

    with engine.connect() as conn:
        seq_row = conn.execute(
            text("SELECT `seq_name`, `last_value` FROM `order_no_seq` WHERE `seq_name` = 'strategy_order'")
        ).first()
        if seq_row:
            print(f"  [OK] generator 'strategy_order' present (last_value={seq_row[1]})")
        else:
            print("  [MISS] generator 'strategy_order' MISSING")

        comment_row = conn.execute(
            text("""
                SELECT COLUMN_COMMENT FROM INFORMATION_SCHEMA.COLUMNS
                 WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'orders' AND COLUMN_NAME = 'strategy_type'
            """),
        ).first()
        comment = (comment_row[0] if comment_row else "") or ""
        marker = "[OK]" if "2=策略下单" in comment else "[MISS]"
        print(f"  {marker} orders.strategy_type COMMENT 已更新 (含 '2=策略下单')")

    engine.dispose()
    print("\n[DONE] v126 母单迁移完成")


if __name__ == "__main__":
    main()
