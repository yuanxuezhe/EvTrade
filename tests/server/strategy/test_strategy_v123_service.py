"""
test_strategy_v123_service.py — 策略/批次/实盘门禁 service 层单测 (v123 change task 6.2)

覆盖:
- 策略 CRUD: create/get/update/delete; 脚本不存在 → NO_SCRIPT; 非本人无权
- 批次生成: single=1 行 task (mode=backtest, status=queued, 挂 batch_no);
  sweep=param_ranges 类型驱动 N 行 (sweep_keys 正确)
- 参数校验: params 含 schema 外字段 → UNKNOWN_PARAM; 组合数 > 512 → GRID_TOO_LARGE
- best 覆盖: list_batches 从 finished tasks 按 metric 聚合 top1; best_params 落库可读
- 实盘门禁: best_params 空/{} → NO_BEST_PARAMS; key 超出 schema → PARAM_MISMATCH;
  有 best_params → 建 1 行 live task (新 batch_no)
- 删除策略级联删 task

DB-backed (dev MySQL), 唯一 test 数据 + teardown 清理, 不做 drop_all。
"""
import os
import sys

import pytest

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.insert(0, _PROJECT_ROOT)
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "server"))

from server.services import script_strategy as svc  # noqa: E402
from server.services.script_strategy import scripts as scripts_svc  # noqa: E402
from server.services.script_strategy.strategies import StrategyError  # noqa: E402
from server.tables import Strategy, StrategyTask, StrategyScript  # noqa: E402
from server.services.script_strategy._convert import json_dumps  # noqa: E402

# 唯一的测试用户/脚本前缀 (避免与真实数据碰撞)
UID = 990010002

SCHEMA = [
    {"key": "fast", "type": "int", "min": 1, "max": 5, "step": 1, "default": 3},
    {"key": "slow", "type": "int", "min": 1, "max": 3, "step": 1, "default": 2},
    {"key": "mode", "type": "choice", "values": ["SMA", "EMA"], "default": "SMA"},
]

_script_seq = [0]


def _new_script_id() -> str:
    _script_seq[0] += 1
    return f"ut_v123_{UID}_{_script_seq[0]}"


def _cleanup_user(user_id: int) -> None:
    """删除该测试用户全部 策略/task/脚本 (幂等)."""
    for s in Strategy.query_by_fields({"user_id": user_id}):
        sid = s._data.get("strategy_id")
        for t in StrategyTask.query_by_fields({"strategy_id": sid}):
            StrategyTask.delete_one(id=t._data["id"])
        Strategy.delete_one(strategy_id=sid)
    for sc in StrategyScript.query_by_fields({"user_id": user_id}):
        StrategyScript.delete_one(user_id=user_id, id=sc._data["id"])


@pytest.fixture(autouse=True)
def _clean(scope="function"):
    _cleanup_user(UID)
    yield
    _cleanup_user(UID)


@pytest.fixture
def strategy_ctx():
    """脚本 + 策略 (同一测试用户), 返回 dict."""
    script_id = _new_script_id()
    scripts_svc.create_script(UID, script_id, "def init(self): pass", SCHEMA)
    strat = svc.create_strategy(UID, f"ut策略-{script_id}", script_id)
    return {"user_id": UID, "script_id": script_id, "strategy_id": strat["strategy_id"]}


# ─────────────── 策略 CRUD ───────────────

def test_create_strategy_draft_no_params(strategy_ctx):
    """建策略只有 {name, script_id}, status=draft, best_params=None."""
    d = svc.get_strategy(strategy_ctx["strategy_id"], UID)
    assert d["status"] == "draft"
    assert d["best_params"] is None
    assert d["script"]["id"] == strategy_ctx["script_id"]


def test_create_strategy_no_script_raises():
    with pytest.raises(StrategyError) as ei:
        svc.create_strategy(UID, "nope", "ut_不存在_脚本")
    assert ei.value.code == "NO_SCRIPT"


def test_update_strategy_name_and_status(strategy_ctx):
    d = svc.update_strategy(strategy_ctx["strategy_id"], UID, False, {"name": "改名", "status": "active"})
    assert d["name"] == "改名"
    assert d["status"] == "active"
    assert d["strategy_id"] == strategy_ctx["strategy_id"]


def test_strategy_cross_user_permission(strategy_ctx):
    """非本人 (别的 user_id) 查不到/删不掉."""
    other = UID + 1
    assert svc.get_strategy(strategy_ctx["strategy_id"], other) is None
    assert svc.update_strategy(strategy_ctx["strategy_id"], other, False, {"name": "x"}) is None
    assert svc.delete_strategy(strategy_ctx["strategy_id"], other, False) is False


def test_delete_strategy_cascades_tasks(strategy_ctx):
    b = svc.create_backtest_batch(
        UID, strategy_ctx["strategy_id"], mode="single",
        stock_code="600519.SH", backtest_start_date="20260101", backtest_end_date="20260131",
        params={"fast": 3, "slow": 2},
    )
    assert len(StrategyTask.query_by_fields({"strategy_id": strategy_ctx["strategy_id"]})) == 1
    assert svc.delete_strategy(strategy_ctx["strategy_id"], UID, False) is True
    assert svc.get_strategy(strategy_ctx["strategy_id"], UID) is None
    assert StrategyTask.query_by_fields({"strategy_id": strategy_ctx["strategy_id"]}) == []


# ─────────────── 批次生成 ───────────────

def test_single_backtest_creates_1_task(strategy_ctx):
    b = svc.create_backtest_batch(
        UID, strategy_ctx["strategy_id"], mode="single",
        stock_code="600519.SH", backtest_start_date="20260101", backtest_end_date="20260131",
        params={"fast": 3, "slow": 2},
    )
    assert b["total_runs"] == 1
    assert len(b["task_ids"]) == 1
    t = StrategyTask.query_one(id=b["task_ids"][0])._data
    assert t["mode"] == "backtest"
    assert t["status"] == "queued"
    assert t["batch_no"] == b["batch_no"]
    assert t["strategy_id"] == strategy_ctx["strategy_id"]
    assert t["params"]  # JSON 列有值


def test_sweep_backtest_creates_n_tasks(strategy_ctx):
    b = svc.create_backtest_batch(
        UID, strategy_ctx["strategy_id"], mode="sweep",
        stock_code="600519.SH", backtest_start_date="20260101", backtest_end_date="20260131",
        param_ranges={"fast": {"type": "int", "start": 1, "end": 3, "step": 1}},
        metric="sharpe", concurrency=2,
    )
    assert b["total_runs"] == 3
    assert b["sweep_keys"] == ["fast"]
    assert len(b["task_ids"]) == 3
    # 每个 combo 的 params 是完整固定值 (未参与字段取 default)
    from server.services.script_strategy._convert import json_loads
    p0 = json_loads(StrategyTask.query_one(id=b["task_ids"][0])._data["params"])
    assert p0["fast"] == 1 and p0["slow"] == 2 and p0["mode"] == "SMA"


def test_single_missing_params_raises(strategy_ctx):
    with pytest.raises(StrategyError) as ei:
        svc.create_backtest_batch(
            UID, strategy_ctx["strategy_id"], mode="single",
            stock_code="600519.SH", backtest_start_date="20260101", backtest_end_date="20260131",
            params=None,
        )
    assert ei.value.code == "MISSING_PARAM"


def test_unknown_param_rejected(strategy_ctx):
    with pytest.raises(StrategyError) as ei:
        svc.create_backtest_batch(
            UID, strategy_ctx["strategy_id"], mode="single",
            stock_code="600519.SH", backtest_start_date="20260101", backtest_end_date="20260131",
            params={"fast": 3, "bogus": 1},
        )
    assert ei.value.code == "UNKNOWN_PARAM"


def test_grid_too_large_rejected(strategy_ctx):
    """30×20 = 600 > 512 → GRID_TOO_LARGE, 不落任何 task."""
    with pytest.raises(StrategyError) as ei:
        svc.create_backtest_batch(
            UID, strategy_ctx["strategy_id"], mode="sweep",
            stock_code="600519.SH", backtest_start_date="20260101", backtest_end_date="20260131",
            param_ranges={
                "fast": {"type": "int", "start": 1, "end": 30, "step": 1},
                "slow": {"type": "int", "start": 1, "end": 20, "step": 1},
            },
        )
    assert ei.value.code == "GRID_TOO_LARGE"
    assert StrategyTask.query_by_fields({"strategy_id": strategy_ctx["strategy_id"]}) == []


# ─────────────── best 覆盖 ───────────────

def test_list_batches_best_from_finished_tasks(strategy_ctx):
    """批次内 finished tasks 按 metric top1 → best_params; failed 不影响."""
    b = svc.create_backtest_batch(
        UID, strategy_ctx["strategy_id"], mode="sweep",
        stock_code="600519.SH", backtest_start_date="20260101", backtest_end_date="20260131",
        param_ranges={"fast": {"type": "int", "start": 1, "end": 3, "step": 1}},
        metric="sharpe", concurrency=2,
    )
    ids = b["task_ids"]
    # 与 strategy_exec _update_task_results 契约一致: 完成时同时写 backtest_result + backtest_metric_value
    StrategyTask.update_one({"status": "finished", "backtest_result": json_dumps({"sharpe": 0.5}), "backtest_metric_value": 0.5}, id=ids[0])
    StrategyTask.update_one({"status": "finished", "backtest_result": json_dumps({"sharpe": 1.5}), "backtest_metric_value": 1.5}, id=ids[1])
    StrategyTask.update_one({"status": "failed", "error_msg": "boom"}, id=ids[2])

    batches = svc.list_batches(strategy_ctx["strategy_id"], UID)
    bb = next(x for x in batches if x["batch_no"] == b["batch_no"])
    assert bb["task_count"] == 3
    assert bb["finished_count"] == 2
    assert bb["failed_count"] == 1
    # top1 = fast=2 (sharpe 1.5), 且未参与字段用 default 补齐
    assert bb["best_params"]["fast"] == 2
    assert bb["best_params"]["slow"] == 2
    assert bb["best_metric_value"] == 1.5


def test_best_params_persist_readable(strategy_ctx):
    """strategy_exec 回写 best_params (Strategy.update_one) → get_strategy 可读."""
    Strategy.update_one(
        {"best_params": json_dumps({"fast": 5, "slow": 2})},
        strategy_id=strategy_ctx["strategy_id"],
    )
    d = svc.get_strategy(strategy_ctx["strategy_id"], UID)
    assert d["best_params"] == {"fast": 5, "slow": 2}


def test_list_batch_tasks_sorted(strategy_ctx):
    b = svc.create_backtest_batch(
        UID, strategy_ctx["strategy_id"], mode="sweep",
        stock_code="600519.SH", backtest_start_date="20260101", backtest_end_date="20260131",
        param_ranges={"fast": {"type": "int", "start": 1, "end": 2, "step": 1}},
    )
    tasks = svc.list_batch_tasks(strategy_ctx["strategy_id"], b["batch_no"], UID)
    ids = [t["id"] for t in tasks]
    assert ids == sorted(ids)
    assert [t["mode"] for t in tasks] == ["backtest", "backtest"]


# ─────────────── 实盘门禁 ───────────────

def test_live_gate_no_best_params(strategy_ctx):
    with pytest.raises(StrategyError) as ei:
        svc.create_live_batch(UID, strategy_ctx["strategy_id"], stock_code="600519.SH")
    assert ei.value.code == "NO_BEST_PARAMS"


def test_live_gate_empty_best_params(strategy_ctx):
    Strategy.update_one(
        {"best_params": json_dumps({})}, strategy_id=strategy_ctx["strategy_id"])
    with pytest.raises(StrategyError) as ei:
        svc.create_live_batch(UID, strategy_ctx["strategy_id"], stock_code="600519.SH")
    assert ei.value.code == "NO_BEST_PARAMS"


def test_live_gate_param_mismatch(strategy_ctx):
    """best_params 含 schema 之外字段 → PARAM_MISMATCH."""
    Strategy.update_one(
        {"best_params": json_dumps({"fast": 3, "slow": 2, "bogus": 1})},
        strategy_id=strategy_ctx["strategy_id"],
    )
    with pytest.raises(StrategyError) as ei:
        svc.create_live_batch(UID, strategy_ctx["strategy_id"], stock_code="600519.SH")
    assert ei.value.code == "PARAM_MISMATCH"


def test_live_success_creates_live_task(strategy_ctx):
    Strategy.update_one(
        {"best_params": json_dumps({"fast": 5, "slow": 2})},
        strategy_id=strategy_ctx["strategy_id"],
    )
    live = svc.create_live_batch(UID, strategy_ctx["strategy_id"], stock_code="600519.SH")
    assert live["mode"] == "live"
    assert live["params"] == {"fast": 5, "slow": 2}
    t = StrategyTask.query_one(id=live["task_id"])._data
    assert t["mode"] == "live"
    assert t["batch_no"] == live["batch_no"]
    assert t["strategy_id"] == strategy_ctx["strategy_id"]
