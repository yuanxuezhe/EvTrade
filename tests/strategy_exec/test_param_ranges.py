"""
strategy_exec 单测 — param_ranges 类型化展开 + 扫描批次 best 回写 (v123, 6.3)

覆盖 (tasks.md 6.3):
- param_ranges 展开含端点: int 含端点步进取整 / float 含端点末位钳制 / choice 值列表 / string 固定
- 16 组合: 2x2x4 笛卡尔积
- 部分失败回写 best: batch 内 finished top1 → update_strategy_best_params
- 全失败不写: 全部 failed → 不写 best_params
- grid > 512 拒绝: validate_grid_size / run_sweep_batch 抛 ValueError, 不触 DB

IO 依赖 (get_batch_tasks / fetch_his_bars / run_backtest / update_strategy_best_params)
全部 monkeypatch, 不连真实 DB。
"""
import asyncio

import pytest

from strategy_exec.engines.backtrader import sweep
from strategy_exec.engines.backtrader.sweep import (
    _expand_values,
    iter_param_ranges,
    count_param_ranges,
    validate_grid_size,
    validate_metric,
    extract_metric_value,
    SWEEP_SOFT_WARN,
    SWEEP_HARD_LIMIT,
)


# ─────────────── _expand_values ───────────────


def test_expand_int_inclusive_endpoints():
    assert _expand_values({"type": "int", "start": 1, "end": 5, "step": 1}) == [1, 2, 3, 4, 5]
    # 未对齐 step 的 end 不包含 (与后端策略一致: int 不钳 end)
    assert _expand_values({"type": "int", "start": 0, "end": 10, "step": 3}) == [0, 3, 6, 9]


def test_expand_float_clamps_end():
    vals = _expand_values({"type": "float", "start": 0, "end": 0.55, "step": 0.1})
    # 0.0,0.1,...,0.5 步进 + 末位钳到 0.55
    assert vals[-1] == 0.55
    assert vals[0] == 0.0
    assert pytest.approx(vals[3]) == 0.3
    # 整除时末位就是 end, 不重复追加
    vals2 = _expand_values({"type": "float", "start": 0, "end": 0.5, "step": 0.1})
    assert vals2[-1] == 0.5
    assert len(vals2) == 6


def test_expand_choice_filters_empty():
    assert _expand_values({"type": "choice", "values": ["SMA", "EMA", ""]}) == ["SMA", "EMA"]


def test_expand_string_fixed():
    assert _expand_values({"type": "string", "value": "abc"}) == ["abc"]
    assert _expand_values({"type": "string", "value": None}) == []


def test_expand_bad_spec_empty():
    assert _expand_values(None) == []
    assert _expand_values({}) == []
    # step 缺失/0 → 兜底 1; start/end 缺失 → 空 (无可用取值)
    assert _expand_values({"type": "int", "start": None, "end": 5, "step": 1}) == []
    assert _expand_values({"type": "float", "start": 1, "end": None, "step": 1}) == []
    assert _expand_values({"type": "bogus", "start": 1, "end": 5}) == []


# ─────────────── iter_param_ranges / count ───────────────


def test_cartesian_product_two_dims():
    combos = list(iter_param_ranges({
        "a": {"type": "int", "start": 1, "end": 2, "step": 1},
        "b": {"type": "int", "start": 10, "end": 30, "step": 10},
    }))
    assert len(combos) == 6
    assert {"a": 1, "b": 10} in combos
    assert {"a": 2, "b": 30} in combos


def test_single_value_param_is_fixed():
    combos = list(iter_param_ranges({
        "a": {"type": "int", "start": 1, "end": 2, "step": 1},   # active: [1,2]
        "b": {"type": "string", "value": "SMA"},                  # fixed
    }))
    assert len(combos) == 2
    for c in combos:
        assert c["b"] == "SMA"
    assert {c["a"] for c in combos} == {1, 2}


def test_all_fixed_single_combo():
    combos = list(iter_param_ranges({
        "a": {"type": "string", "value": "SMA"},
        "b": {"type": "string", "value": "1d"},
    }))
    assert combos == [{"a": "SMA", "b": "1d"}]


def test_empty_ranges_one_combo():
    assert list(iter_param_ranges({})) == [{}]
    assert list(iter_param_ranges(None)) == [{}]


def test_count_16_combos():
    n = count_param_ranges({
        "a": {"type": "int", "start": 1, "end": 2, "step": 1},
        "b": {"type": "int", "start": 1, "end": 2, "step": 1},
        "c": {"type": "int", "start": 1, "end": 4, "step": 1},
    })
    assert n == 16  # 2 * 2 * 4


# ─────────────── validate_grid_size / metric ───────────────


def test_grid_at_hard_limit_ok():
    validate_grid_size(SWEEP_HARD_LIMIT)  # 不抛


def test_grid_over_hard_limit_rejected():
    with pytest.raises(ValueError):
        validate_grid_size(SWEEP_HARD_LIMIT + 1)


def test_grid_over_soft_warn_ok(caplog):
    with caplog.at_level("WARNING", logger="strategy_exec.engines.backtrader.sweep"):
        validate_grid_size(SWEEP_SOFT_WARN + 1)
    assert any("软警告" in r.message for r in caplog.records)


def test_validate_metric():
    validate_metric("sharpe")
    validate_metric("total_return")
    validate_metric("calmar")
    with pytest.raises(ValueError):
        validate_metric("sortino")


# ─────────────── extract_metric_value ───────────────


def test_metric_sharpe():
    assert extract_metric_value({"sharpe": 1.5}, "sharpe") == 1.5
    assert extract_metric_value({"sharpe": None}, "sharpe") is None
    assert extract_metric_value(None, "sharpe") is None


def test_metric_total_return():
    assert extract_metric_value({"pnl": 5000, "initial_cash": 100000}, "total_return") == 0.05
    assert extract_metric_value({"pnl": None}, "total_return") is None


def test_metric_calmar():
    r = {"pnl": 1000, "initial_cash": 100000, "max_drawdown": 0.1}
    assert pytest.approx(extract_metric_value(r, "calmar")) == 0.1
    # max_drawdown=0 → None
    r2 = {"pnl": 1000, "initial_cash": 100000, "max_drawdown": 0.0}
    assert extract_metric_value(r2, "calmar") is None


# ─────────────── run_sweep_batch: 部分失败回写 best / 全失败不写 ───────────────


def _run(batch_kwargs):
    """用 monkeypatch 的 IO 跑 run_sweep_batch (pytest monkeypatch 在 test 内注入)."""
    return asyncio.run(sweep.run_sweep_batch(**batch_kwargs))


async def _fake_fetch_his_bars(**kw):
    return [{"date": "20260101", "close": 1.0}]


def _mk_run_backtest(results_by_task):
    """按 task_id 返回 {result} 或 raise"""
    def _run_backtest(task_id=None, **kw):
        r = results_by_task.get(task_id)
        if isinstance(r, Exception):
            raise r
        return r
    return _run_backtest


TASKS = [
    {"id": 1, "params": {"a": 1}},
    {"id": 2, "params": {"a": 2}},
    {"id": 3, "params": {"a": 3}},
]

BASE_KW = dict(
    strategy_id=100, batch_no=1, user_id=1, script_id="script-x",
    stock_code="600519.SH", metric="sharpe",
    backtest_start_date="20260101", backtest_end_date="20260131",
    concurrency=2,
    param_ranges={"a": {"type": "int", "start": 1, "end": 3, "step": 1}},  # 3 组合, 匹配 TASKS
)


def test_sweep_partial_failure_writes_best(monkeypatch):
    monkeypatch.setattr(sweep, "get_batch_tasks", lambda sid, bn: TASKS)
    monkeypatch.setattr(sweep, "fetch_his_bars", _fake_fetch_his_bars)
    monkeypatch.setattr(sweep, "run_backtest", _mk_run_backtest({
        1: {"sharpe": 0.5},
        2: {"sharpe": 1.5},
        3: RuntimeError("boom"),
    }))
    calls = []
    monkeypatch.setattr(sweep, "update_strategy_best_params",
                        lambda sid, bp: calls.append((sid, bp)))

    result = _run(BASE_KW)

    assert result["succeeded"] == 2
    assert result["failed"] == 1
    assert result["best_params"] == {"a": 2}      # metric top1
    assert result["best_metric_value"] == 1.5
    assert calls == [(100, {"a": 2})]             # 只写一次, 参数为 top1


def test_sweep_all_fail_no_write(monkeypatch):
    monkeypatch.setattr(sweep, "get_batch_tasks", lambda sid, bn: TASKS)
    monkeypatch.setattr(sweep, "fetch_his_bars", _fake_fetch_his_bars)
    monkeypatch.setattr(sweep, "run_backtest", _mk_run_backtest({
        1: RuntimeError("a"), 2: RuntimeError("b"), 3: RuntimeError("c"),
    }))
    calls = []
    monkeypatch.setattr(sweep, "update_strategy_best_params",
                        lambda sid, bp: calls.append((sid, bp)))

    result = _run(BASE_KW)

    assert result["succeeded"] == 0
    assert result["failed"] == 3
    assert result["best_params"] is None
    assert calls == []                            # 全失败不写


def test_sweep_grid_over_hard_limit_rejected_before_db(monkeypatch):
    """600 组合 (>512) → ValueError, get_batch_tasks 不被调用"""
    called = []
    monkeypatch.setattr(sweep, "get_batch_tasks",
                        lambda sid, bn: called.append((sid, bn)) or TASKS)

    with pytest.raises(ValueError):
        _run({
            **BASE_KW,
            "param_ranges": {
                "a": {"type": "int", "start": 1, "end": 20, "step": 1},    # 20
                "b": {"type": "int", "start": 1, "end": 30, "step": 1},    # 30 → 600
            },
        })

    assert called == []
