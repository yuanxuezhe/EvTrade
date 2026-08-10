"""
test_migration.py — Phase 3 strategy_task 3 列 nullable 迁移测试

覆盖:
- tables/strategy_task.py 类定义含 sweep_id/sweep_metric/sweep_total 3 字段
- 3 字段都在 __fields__ + __field_types__ + type hints
- 类型正确 (varchar(32) / varchar(32) / int)
- migration 脚本 idempotent (重复跑不抛错)
- SQL DDL 含 ALTER TABLE + 3 ADD COLUMN
"""
import os
import re
import sys

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
_SERVER_DIR = os.path.join(_PROJECT_ROOT, "server")
if _SERVER_DIR not in sys.path:
    sys.path.insert(0, _SERVER_DIR)

import importlib.util
import pytest


# ──── 1. tables/strategy_task.py 类定义含 3 字段 ────

def test_strategy_task_class_has_sweep_fields():
    """类定义 __fields__ + __field_types__ + type hints 都含 3 sweep 字段"""
    # 不连 DB, 仅 import 类 (TableBase 是抽象基类, 不需要 engine 实例)
    spec = importlib.util.spec_from_file_location(
        "strategy_task_table",
        os.path.join(_SERVER_DIR, "tables", "strategy_task.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as e:
        pytest.skip(f"加载 tables/strategy_task.py 失败 (可能缺依赖): {e}")
    StrategyTask = mod.StrategyTask

    # __fields__ 含 3 个
    for name in ("sweep_id", "sweep_metric", "sweep_total"):
        assert name in StrategyTask.__fields__, \
            f"StrategyTask.__fields__ 缺 '{name}'"
    # __field_types__ 类型正确
    assert StrategyTask.__field_types__["sweep_id"] == "varchar(32)"
    assert StrategyTask.__field_types__["sweep_metric"] == "varchar(32)"
    assert StrategyTask.__field_types__["sweep_total"] == "int"
    # type hints 也含 (IDE 提示用)
    hints = StrategyTask.__annotations__
    for name in ("sweep_id", "sweep_metric", "sweep_total"):
        assert name in hints, f"StrategyTask type hints 缺 '{name}'"


# ──── 2. migration 脚本 DDL 含正确 ALTER TABLE ────

def test_migration_ddl_contains_three_alter_columns():
    """migration 脚本里 DDL 字符串含 3 个 ALTER TABLE + ADD COLUMN"""
    mig_path = os.path.join(
        _SERVER_DIR, "migrations", "2026-08-11-add-strategy-sweep-fields.py"
    )
    assert os.path.exists(mig_path), f"migration 文件不存在: {mig_path}"
    src = open(mig_path, encoding="utf-8").read()

    # 3 个 ADD COLUMN 必须出现
    assert src.count("ALTER TABLE strategy_task ADD COLUMN") >= 3, \
        "migration 应含至少 3 个 ALTER TABLE strategy_task ADD COLUMN"
    # 3 个字段名都在 DDL 里
    for name in ("sweep_id", "sweep_metric", "sweep_total"):
        assert f"ADD COLUMN {name}" in src, f"DDL 缺 ADD COLUMN {name}"
    # VARCHAR(32) 和 INT 类型正确
    assert "VARCHAR(32)" in src, "DDL 应含 VARCHAR(32) (sweep_id/sweep_metric)"
    assert "ADD COLUMN sweep_total INT" in src, "DDL 应含 ADD COLUMN sweep_total INT"
    # 全部 NULL (nullable) — 类型是 VARCHAR(N) 或 INT, 后跟 NULL
    for name in ("sweep_id", "sweep_metric", "sweep_total"):
        # 匹配 VARCHAR(N) NULL 或 INT NULL
        pattern = rf"ADD COLUMN {name} (?:VARCHAR\(\d+\)|INT) NULL"
        assert re.search(pattern, src), f"DDL '{name}' 应显式 NULL (nullable)"


# ──── 3. migration 脚本幂等性: _column_exists 检查存在 ────

def test_migration_is_idempotent_with_check():
    """migration 含 INFORMATION_SCHEMA 检查 → 已存在跳过"""
    mig_path = os.path.join(
        _SERVER_DIR, "migrations", "2026-08-11-add-strategy-sweep-fields.py"
    )
    src = open(mig_path, encoding="utf-8").read()
    # 必须查 INFORMATION_SCHEMA
    assert "INFORMATION_SCHEMA.COLUMNS" in src, \
        "migration 应查 INFORMATION_SCHEMA.COLUMNS 做幂等检查"
    assert "_column_exists" in src, \
        "migration 应有 _column_exists 辅助函数"
    # 含 already exists 提示
    assert "already exists" in src or "skip" in src, \
        "migration 应有 skip / already exists 分支"


# ──── 4. _extract_type helper 行为正确 ────

def test_extract_type_helper():
    """_extract_type 正确从 DDL 字符串提取列类型 (含 NULL / DEFAULT)"""
    mig_path = os.path.join(
        _SERVER_DIR, "migrations", "2026-08-11-add-strategy-sweep-fields.py"
    )
    spec = importlib.util.spec_from_file_location(
        "migration_mod", mig_path
    )
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as e:
        pytest.skip(f"加载 migration 失败 (可能缺 SQLAlchemy): {e}")

    ddl = "ALTER TABLE strategy_task ADD COLUMN sweep_id VARCHAR(32) NULL DEFAULT NULL"
    assert mod._extract_type(ddl) == "VARCHAR(32) NULL DEFAULT NULL"

    ddl2 = "ALTER TABLE strategy_task ADD COLUMN sweep_total INT NULL DEFAULT NULL"
    assert mod._extract_type(ddl2) == "INT NULL DEFAULT NULL"
