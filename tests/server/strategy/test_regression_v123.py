"""
test_regression_v123.py — 回归测试 (v123 change task 6.5)

覆盖:
- next_order_no 委托 next_seq('order_no') 行为不变: 连续递增、8 位数字
- 序号表多生成器互不干扰: order_no / task_batch 各自独立 +1
- 现有单次回测行为不变: mode=backtest 恰好 1 行 task (queued, 挂 strategy_id+batch_no),
  批次列表/批次任务/任务详情都可查

DB-backed (dev MySQL), 唯一 test 数据 + teardown 清理。
"""
import os
import sys

import pytest

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.insert(0, _PROJECT_ROOT)
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "server"))

from server.repo.orders import next_seq, next_order_no  # noqa: E402
from server.services import script_strategy as svc  # noqa: E402
from server.services.script_strategy import scripts as scripts_svc  # noqa: E402
from server.services.script_strategy.tasks import get_task  # noqa: E402
from server.tables import Strategy, StrategyTask, StrategyScript  # noqa: E402

UID = 990010004

SCHEMA = [
    {"key": "fast", "type": "int", "min": 1, "max": 5, "step": 1, "default": 3},
    {"key": "slow", "type": "int", "min": 1, "max": 3, "step": 1, "default": 2},
]

_script_seq = [0]


def _new_script_id() -> str:
    _script_seq[0] += 1
    return f"ut_reg_{UID}_{_script_seq[0]}"


def _cleanup_user(user_id: int) -> None:
    for s in Strategy.query_by_fields({"user_id": user_id}):
        sid = s._data.get("strategy_id")
        for t in StrategyTask.query_by_fields({"strategy_id": sid}):
            StrategyTask.delete_one(id=t._data["id"])
        Strategy.delete_one(strategy_id=sid)
    for sc in StrategyScript.query_by_fields({"user_id": user_id}):
        StrategyScript.delete_one(user_id=user_id, id=sc._data["id"])


@pytest.fixture(autouse=True)
def _clean():
    _cleanup_user(UID)
    yield
    _cleanup_user(UID)


# ─────────────── next_order_no / 序号表回归 ───────────────

def test_next_order_no_still_sequential():
    """next_order_no 委托 next_seq('order_no'), 连续 2 次严格 +1, 8 位数字."""
    n1, n2 = next_order_no(), next_order_no()
    assert n1.isdigit() and n2.isdigit()
    assert len(n1) == 8 and len(n2) == 8
    assert int(n2) == int(n1) + 1


def test_next_seq_uses_same_generator_as_order_no():
    """next_seq('order_no') 与 next_order_no 同 generator, 交替调用也严格 +1."""
    a = next_order_no()
    b = next_seq("order_no")
    assert int(b) == int(a) + 1


def test_multi_generator_independent():
    """order_no 与 task_batch 各自独立 +1, 互不干扰 (v123 泛化回归)."""
    o1, t1 = next_seq("order_no"), next_seq("task_batch")
    o2, t2 = next_seq("order_no"), next_seq("task_batch")
    assert int(o2) == int(o1) + 1
    assert int(t2) == int(t1) + 1
    # 两个生成器互不覆盖
    assert {next_seq("order_no"), next_seq("task_batch")} == {str(int(o2) + 1), str(int(t2) + 1)}


# ─────────────── 单次回测回归: mode=backtest 1 行 task 可跑可查 ───────────────

def test_single_backtest_one_task_queryable():
    script_id = _new_script_id()
    scripts_svc.create_script(UID, script_id, "def init(self): pass", SCHEMA)
    strat = svc.create_strategy(UID, "回归策略", script_id, stock_code="600519.SH")
    sid = strat["strategy_id"]

    b = svc.create_backtest_batch(
        UID, sid, mode="single", stock_code="600519.SH",
        backtest_start_date="20260101", backtest_end_date="20260131",
        params={"fast": 3, "slow": 2},
    )
    assert b["total_runs"] == 1
    task_id = b["task_ids"][0]

    # 可查: 任务详情
    t = get_task(task_id, UID)
    assert t["id"] == task_id
    assert t["mode"] == "backtest"
    assert t["status"] == "queued"
    assert t["strategy_id"] == sid
    assert t["batch_no"] == b["batch_no"]
    assert t["params"] == {"fast": 3, "slow": 2}

    # 可查: 批次列表
    batches = svc.list_batches(sid, UID)
    bb = next(x for x in batches if x["batch_no"] == b["batch_no"])
    assert bb["task_count"] == 1
    assert bb["mode"] == "backtest"

    # 可查: 批次内任务表格
    tasks = svc.list_batch_tasks(sid, b["batch_no"], UID)
    assert len(tasks) == 1
    assert tasks[0]["id"] == task_id
