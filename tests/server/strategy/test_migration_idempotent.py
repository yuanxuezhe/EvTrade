"""
test_migration_idempotent.py — 迁移脚本幂等自测 (v123 change strategy-batch-task-model task 6.1)

覆盖:
- order_no_seq 多生成器迁移 (2026-08-11-order-no-seq-multi-generator.py)
- strategy 表 + strategy_task 重构迁移 (2026-08-11-add-strategy-table-refactor-task.py)

断言:
- 结构不变式: order_no_seq 以 seq_name 为 PK + order_no/task_batch 生成器;
  strategy 表 PK=strategy_id + 必要列; strategy_task 有 strategy_id/batch_no、
  旧列已删、聚合索引存在
- 数据不变式: 每个 task 都有 strategy_id + batch_no; 每个 (user_id, script_id)
  至多一个 strategy (回填去重)
- 幂等: 对已迁移的 dev DB 再跑一次 main() → 不抛错、不产生重复、不改变结构

⚠️ DB-backed: 需要 EVTRADE_DB_URL (dev MySQL, MySQL-only 永久标准)。
"""
import importlib.util
import os
import sys

import pytest
from sqlalchemy import create_engine, inspect, text

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.insert(0, _PROJECT_ROOT)
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "server"))

from server.infra.db import engine as app_engine  # noqa: E402

MIG_SEQ = os.path.join(_PROJECT_ROOT, "server", "migrations", "2026-08-11-order-no-seq-multi-generator.py")
MIG_STRATEGY = os.path.join(_PROJECT_ROOT, "server", "migrations", "2026-08-11-add-strategy-table-refactor-task.py")
MIG_VISIBILITY = os.path.join(
    _PROJECT_ROOT, "server", "migrations", "2026-08-11-add-strategy-visibility.py")


def _load(modname: str, path: str):
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mig():
    """加载两个迁移模块 (模块级 engine 只在 import 时创建, main() 才连库)."""
    return _load("mig_seq", MIG_SEQ), _load("mig_strategy", MIG_STRATEGY)


def _run_ok(mod) -> None:
    """跑迁移 main(), 失败(sys.exit(1)) 视为测试失败."""
    try:
        mod.main()
    except SystemExit as e:
        pytest.fail(f"migration main() 验证失败 (exit {e.code})")


def _seq_invariants() -> None:
    insp = inspect(app_engine)
    cols = {c["name"] for c in insp.get_columns("order_no_seq")}
    assert {"seq_name", "last_value", "updated_at"} <= cols, f"order_no_seq 缺列: {cols}"
    assert "id" not in cols, "order_no_seq 不应再有旧 id 列"
    assert insp.get_pk_constraint("order_no_seq")["constrained_columns"] == ["seq_name"], \
        "order_no_seq PK 应为 seq_name"
    with app_engine.connect() as conn:
        rows = {
            r.seq_name: r.last_value
            for r in conn.execute(text("SELECT `seq_name`, `last_value` FROM order_no_seq"))
        }
    assert "order_no" in rows and "task_batch" in rows, \
        f"应含 order_no + task_batch 生成器, 实际: {sorted(rows)}"


def _strategy_invariants() -> int:
    """返回当前 strategy_task 总数 (幂等复跑前后对比用)."""
    insp = inspect(app_engine)
    sc = {c["name"] for c in insp.get_columns("strategy")}
    assert {"strategy_id", "user_id", "script_id", "name", "status", "best_params"} <= sc, \
        f"strategy 表缺列: {sc}"
    assert insp.get_pk_constraint("strategy")["constrained_columns"] == ["strategy_id"], \
        "strategy PK 应为 strategy_id"
    tc = {c["name"] for c in insp.get_columns("strategy_task")}
    assert {"strategy_id", "batch_no"} <= tc, f"strategy_task 缺 strategy_id/batch_no: {tc}"
    gone = {"script_id", "best_params", "sweep_id", "sweep_total", "sweep_metric"}
    assert not (gone & tc), f"strategy_task 旧列未删干净: {sorted(gone & tc)}"
    idx = {i["name"] for i in insp.get_indexes("strategy_task")}
    assert "ix_strategy_task_batch" in idx, "缺聚合索引 ix_strategy_task_batch"

    with app_engine.connect() as conn:
        n = conn.execute(text("SELECT COUNT(*) FROM strategy_task")).scalar()
        null_sid = conn.execute(text("SELECT COUNT(*) FROM strategy_task WHERE strategy_id IS NULL")).scalar()
        null_bn = conn.execute(text("SELECT COUNT(*) FROM strategy_task WHERE batch_no IS NULL")).scalar()
        dup = conn.execute(text(
            "SELECT user_id, script_id, COUNT(*) c FROM `strategy` "
            "GROUP BY user_id, script_id HAVING c > 1"
        )).fetchall()
    assert null_sid == 0, f"{null_sid} 个 task 缺 strategy_id (回填不完整)"
    assert null_bn == 0, f"{null_bn} 个 task 缺 batch_no (回填不完整)"
    assert not dup, f"存在重复 strategy (回填未去重): {dup}"
    return n


# ─────────────── 结构不变式 (read-only) ───────────────

def test_seq_migration_structure_invariants(mig):
    """order_no_seq 已是 seq_name PK 多生成器表, 含 order_no/task_batch."""
    _seq_invariants()


def test_strategy_migration_structure_invariants(mig):
    """strategy 表 + strategy_task 重构后的结构/数据不变式."""
    _strategy_invariants()


# ─────────────── 幂等复跑 (对已迁移 dev DB 再跑一次) ───────────────

def test_seq_migration_reapply_idempotent(mig):
    """order_no_seq 迁移再跑一次 → 不抛错, 生成器仍恰好 2 个, last_value 不变."""
    seq_mod, _ = mig
    with app_engine.connect() as conn:
        before = {
            r.seq_name: r.last_value
            for r in conn.execute(text("SELECT `seq_name`, `last_value` FROM order_no_seq"))
        }
    _run_ok(seq_mod)
    _seq_invariants()
    with app_engine.connect() as conn:
        after = {
            r.seq_name: r.last_value
            for r in conn.execute(text("SELECT `seq_name`, `last_value` FROM order_no_seq"))
        }
    assert before == after, f"幂等复跑不应改 last_value: {before} -> {after}"
    assert set(after) == {"order_no", "task_batch"}


def test_strategy_migration_reapply_idempotent(mig):
    """strategy/strategy_task 迁移再跑一次 → 不抛错, task 数不变, 不产生重复 strategy."""
    _, strat_mod = mig
    before_tasks = _strategy_invariants()
    _run_ok(strat_mod)
    after_tasks = _strategy_invariants()
    assert before_tasks == after_tasks, \
        f"幂等复跑不应新增/删除 task: {before_tasks} -> {after_tasks}"


def test_visibility_migration_reapply_idempotent():
    """strategy 可见性迁移再跑一次 → 不抛错, 新列仍在."""
    vis_mod = _load("mig_visibility", MIG_VISIBILITY)
    cols = {c["name"] for c in inspect(app_engine).get_columns("strategy")}
    assert {"is_public", "stock_code"} <= cols, f"strategy 缺 v125 列: {cols}"
    _run_ok(vis_mod)
    cols2 = {c["name"] for c in inspect(app_engine).get_columns("strategy")}
    assert {"is_public", "stock_code"} <= cols2
