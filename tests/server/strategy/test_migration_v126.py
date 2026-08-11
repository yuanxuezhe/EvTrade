"""
test_migration_v126.py — v126 母单迁移幂等测试

验证 server/migrations/2026-08-11-add-strategy-order.py:
1. 第一次跑: 表/索引/序列/COMMENT 全部就位
2. 第二次跑: 不报错, 不创建重复对象
3. 生成器可读 (next_seq('strategy_order', db) 返回递增 int)
"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest
from sqlalchemy import create_engine, inspect, text

DATABASE_URL = os.environ.get("EVTRADE_DB_URL")
if not DATABASE_URL:
    pytest.skip("EVTRADE_DB_URL 未设置, 跳过迁移集成测试", allow_module_level=True)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
MIGRATION = os.path.join(REPO_ROOT, "server", "migrations", "2026-08-11-add-strategy-order.py")


def _run_migration() -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, MIGRATION],
        cwd=REPO_ROOT,
        env={**os.environ},
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_migration_runs_and_is_idempotent():
    """第一次跑 + 第二次跑都成功, 表/索引/序列/COMMENT 一致."""
    r1 = _run_migration()
    assert r1.returncode == 0, f"first run failed:\nstdout={r1.stdout}\nstderr={r1.stderr}"
    assert "[DONE] v126 母单迁移完成" in r1.stdout

    r2 = _run_migration()
    assert r2.returncode == 0, f"second run failed (not idempotent):\nstdout={r2.stdout}\nstderr={r2.stderr}"
    assert "[skip] table 'strategy_order' already exists" in r2.stdout
    assert "[skip] 'strategy_order' generator already exists" in r2.stdout
    assert "[skip] orders.strategy_type COMMENT already up-to-date" in r2.stdout


def test_strategy_order_table_structure():
    """验证 strategy_order 表结构: 7+ 列, 3 索引."""
    insp = inspect(engine)
    assert "strategy_order" in insp.get_table_names()

    cols = {c["name"]: c for c in insp.get_columns("strategy_order")}
    # PK 用 get_pk_constraint 探测 (老 SQLAlchemy get_columns 不含 primary_key 字段)
    pk = insp.get_pk_constraint("strategy_order")
    assert "id" in pk["constrained_columns"], f"PK 应含 id, got {pk}"

    for required in ("id", "task_id", "user_id", "strategy_id", "stock_code", "status",
                     "active_task_id", "run_count", "last_started_at", "last_stopped_at",
                     "closed_at", "created_at", "updated_at"):
        assert required in cols, f"missing column '{required}'"
    assert "stopped" in str(cols["status"]["default"]), f"status default 应含 'stopped', got {cols['status']['default']!r}"
    assert "0" in str(cols["run_count"]["default"]), f"run_count default 应为 0, got {cols['run_count']['default']!r}"

    indexes = {i["name"]: i for i in insp.get_indexes("strategy_order")}
    for required in ("uk_strategy_order_task_id", "ix_strategy_order_user_id", "ix_strategy_order_strategy_id"):
        assert required in indexes, f"missing index '{required}'"
    # UNIQUE 索引 uk_strategy_order_task_id 的列唯一
    assert indexes["uk_strategy_order_task_id"]["unique"] is True
    assert indexes["uk_strategy_order_task_id"]["column_names"] == ["task_id"]


def test_strategy_order_generator_present():
    """验证 order_no_seq.strategy_order 生成器行存在."""
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT `seq_name`, `last_value` FROM `order_no_seq` WHERE `seq_name` = 'strategy_order'")
        ).first()
    assert row is not None, "order_no_seq.strategy_order 行缺失"
    assert row[0] == "strategy_order"
    assert isinstance(row[1], int)
    assert row[1] >= 0


def test_orders_strategy_type_comment_updated():
    """验证 orders.strategy_type COMMENT 含 2=策略下单."""
    with engine.connect() as conn:
        row = conn.execute(
            text("""
                SELECT COLUMN_COMMENT FROM INFORMATION_SCHEMA.COLUMNS
                 WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'orders' AND COLUMN_NAME = 'strategy_type'
            """),
        ).first()
    assert row is not None
    assert "2=策略下单" in (row[0] or ""), f"COMMENT 未更新: {row[0]!r}"


def test_next_seq_strategy_order_returns_unique():
    """next_seq('strategy_order') 返回递增 int, 多次调用值不同."""
    from server.repo.orders import next_seq

    v1 = int(next_seq("strategy_order"))
    v2 = int(next_seq("strategy_order"))
    assert v1 > 0 and v2 > 0
    assert v2 > v1, f"next_seq 应当单调递增, got v1={v1} v2={v2}"
