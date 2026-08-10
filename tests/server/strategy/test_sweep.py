"""
test_sweep.py — Phase 4 sweep 引擎测试

覆盖 REQ-SE-008 of `2026-08-10-strategy-params-sweep-best-live`:
- iter_param_grid 笛卡尔积正确性 (单值字段跳过 / 多字段组合 / 空 grid)
- count_grid_size 算总组合数
- validate_grid_size 软警告 + 硬拒绝
- validate_metric 白名单
- extract_metric_value sharpe / total_return / calmar
- run_sweep 端到端: 4 组合全成功 + 部分失败 (mock backtest + DB)

注: 仓库未装 pytest-asyncio, run_sweep 是 async — 用 asyncio.run() 包装为 sync 测试.
"""
import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

# 把 strategy_exec/ 加进 sys.path
_STRATEGY_EXEC_DIR = os.path.join(
    os.path.dirname(__file__), '..', '..', '..', 'strategy_exec'
)
if _STRATEGY_EXEC_DIR not in sys.path:
    sys.path.insert(0, _STRATEGY_EXEC_DIR)

import pytest

from strategy_exec.engines.backtrader.sweep import (
    iter_param_grid, count_grid_size,
    validate_grid_size, validate_metric,
    extract_metric_value, generate_sweep_id,
    run_sweep,
    SWEEP_SOFT_WARN, SWEEP_HARD_LIMIT,
)


def _run(coro):
    """同步包装 async coroutine (仓库无 pytest-asyncio, 用 asyncio.run)"""
    return asyncio.run(coro)


# ──── 1. iter_param_grid 笛卡尔积 ────

def test_iter_param_grid_cartesian_basic():
    """2 字段 4×4 = 16 组合"""
    grid = {"fast": [3, 5, 7, 10], "slow": [15, 20, 30, 60]}
    combos = list(iter_param_grid(grid))
    assert len(combos) == 16
    # 验证每组合都含 fast + slow
    for c in combos:
        assert "fast" in c and "slow" in c
    # 验证极端值
    assert {"fast": 3, "slow": 15} in combos
    assert {"fast": 10, "slow": 60} in combos


def test_iter_param_grid_skip_single_value_fields():
    """单值字段不参与笛卡尔积, 但保留在每组合里"""
    grid = {"fast": [3, 5, 7], "slow": [20], "qty": [100]}
    combos = list(iter_param_grid(grid))
    assert len(combos) == 3  # 只 fast 笛卡尔
    for c in combos:
        assert c["slow"] == 20
        assert c["qty"] == 100
        assert c["fast"] in [3, 5, 7]


def test_iter_param_grid_all_single_value():
    """全部单值 → 1 个组合"""
    grid = {"fast": [5], "slow": [20]}
    combos = list(iter_param_grid(grid))
    assert combos == [{"fast": 5, "slow": 20}]


def test_iter_param_grid_empty_grid():
    """空 grid → 1 个空 dict 组合"""
    assert list(iter_param_grid({})) == [{}]


def test_iter_param_grid_empty_list_values():
    """某字段空 list → 当未配置跳过"""
    grid = {"fast": [3, 5], "slow": []}
    combos = list(iter_param_grid(grid))
    # slow 空 list 跳过, 只 fast 笛卡尔 → 2 组合
    assert len(combos) == 2
    for c in combos:
        assert "slow" not in c


# ──── 2. count_grid_size ────

def test_count_grid_size_matches_iter():
    """count_grid_size 与 iter_param_grid 长度一致"""
    grid = {"fast": [3, 5, 7, 10], "slow": [15, 20, 30, 60]}
    assert count_grid_size(grid) == 16
    assert count_grid_size(grid) == len(list(iter_param_grid(grid)))


def test_count_grid_size_single_value_fields_not_counted():
    """单值字段不参与乘法"""
    grid = {"fast": [3, 5, 7], "slow": [20], "qty": [100]}
    assert count_grid_size(grid) == 3  # 只 fast 算


def test_count_grid_size_empty_grid_returns_one():
    """空 grid → 1 个组合"""
    assert count_grid_size({}) == 1


def test_count_grid_size_empty_list_skipped():
    """空 list 字段不参与"""
    assert count_grid_size({"a": [], "b": [1, 2]}) == 2


# ──── 3. validate_grid_size ────

def test_validate_grid_size_under_soft_no_warning(caplog):
    """小于软警告 (64) → 不警告不抛错"""
    caplog.set_level("WARNING", logger="strategy_exec.engines.backtrader.sweep")
    validate_grid_size(32)  # 应不抛
    assert not any("软警告" in r.message for r in caplog.records)


def test_validate_grid_size_over_soft_warns(caplog):
    """超过软警告 (64) → log warning, 不抛错"""
    caplog.set_level("WARNING", logger="strategy_exec.engines.backtrader.sweep")
    validate_grid_size(100)
    assert any("软警告" in r.message for r in caplog.records)


def test_validate_grid_size_over_hard_raises():
    """超过硬拒绝 (512) → ValueError"""
    with pytest.raises(ValueError, match="硬上限"):
        validate_grid_size(513)


def test_validate_grid_size_at_hard_boundary_ok():
    """恰好 512 → 通过 (硬拒绝是 >, 不是 >=)"""
    validate_grid_size(512)  # 应不抛


# ──── 4. validate_metric ────

def test_validate_metric_allowed():
    """sharpe / total_return / calmar → OK"""
    for m in ("sharpe", "total_return", "calmar"):
        validate_metric(m)  # 不抛


def test_validate_metric_rejects_unknown():
    """未知 metric → ValueError"""
    with pytest.raises(ValueError, match="metric 必须是"):
        validate_metric("foo_bar")


# ──── 5. extract_metric_value ────

def test_extract_metric_value_sharpe():
    """metric='sharpe' → 取 result.sharpe"""
    result = {"sharpe": 1.82, "pnl": 1000, "initial_cash": 100000}
    assert extract_metric_value(result, "sharpe") == 1.82


def test_extract_metric_value_sharpe_missing_returns_none():
    """无 sharpe → None"""
    assert extract_metric_value({"pnl": 1000}, "sharpe") is None
    assert extract_metric_value({}, "sharpe") is None


def test_extract_metric_value_total_return():
    """metric='total_return' → pnl / initial_cash"""
    result = {"pnl": 5000, "initial_cash": 100000}
    assert extract_metric_value(result, "total_return") == 0.05


def test_extract_metric_value_total_return_default_cash():
    """无 initial_cash → 默认 100000"""
    result = {"pnl": 10000}
    assert extract_metric_value(result, "total_return") == 0.1


def test_extract_metric_value_calmar():
    """calmar = total_return / max_drawdown"""
    result = {"pnl": 10000, "initial_cash": 100000, "max_drawdown": 0.05}
    # total_return = 10000/100000 = 0.1, calmar = 0.1 / 0.05 = 2.0
    assert extract_metric_value(result, "calmar") == 2.0


def test_extract_metric_value_calmar_zero_dd_returns_none():
    """max_drawdown = 0 → None (避免除零)"""
    result = {"pnl": 10000, "initial_cash": 100000, "max_drawdown": 0.0}
    assert extract_metric_value(result, "calmar") is None


def test_extract_metric_value_empty_result_returns_none():
    """空 result → None (任何 metric)"""
    for m in ("sharpe", "total_return", "calmar"):
        assert extract_metric_value({}, m) is None
        assert extract_metric_value(None, m) is None


# ──── 6. generate_sweep_id ────

def test_generate_sweep_id_length_and_uniqueness():
    """sweep_id 32 字符 hex, 多次调用全不同"""
    ids = {generate_sweep_id() for _ in range(100)}
    assert len(ids) == 100  # 全唯一
    for sid in ids:
        assert len(sid) == 32
        assert all(c in "0123456789abcdef" for c in sid)


# ──── 7. run_sweep 端到端 (mock backtest + DB) ────

def test_run_sweep_4_combos_all_success(monkeypatch):
    """4 组合全成功 → summary 写 best_params = sharpe 最高"""
    from strategy_exec.engines.backtrader import sweep as sweep_mod

    # Mock fetch_his_bars
    fake_bars = [{"open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 100, "stime": "20260101093000"}]
    monkeypatch.setattr(sweep_mod, "fetch_his_bars", AsyncMock(return_value=fake_bars))

    # Mock create_sweep_task: 返递增 id
    _task_id_counter = [1000]
    def fake_create_sweep_task(**kwargs):
        _task_id_counter[0] += 1
        return _task_id_counter[0]
    monkeypatch.setattr(sweep_mod, "create_sweep_task", fake_create_sweep_task)

    # Mock run_backtest: 返 sharpe 取决于 fast
    def fake_run_backtest(**kwargs):
        params = kwargs["params"]
        return {
            "pnl": 1000 * params["fast"],
            "initial_cash": 100000,
            "sharpe": 0.5 + params["fast"] * 0.1,  # fast 越大 sharpe 越高
        }
    monkeypatch.setattr(sweep_mod, "run_backtest", fake_run_backtest)

    # Mock update_sweep_summary: 捕获入参
    captured = {}
    def fake_update_sweep_summary(**kwargs):
        captured["sweep_results"] = kwargs["sweep_results"]
        captured["best_params"] = kwargs["best_params"]
        captured["best_metric_value"] = kwargs["best_metric_value"]
        return True
    monkeypatch.setattr(sweep_mod, "update_sweep_summary", fake_update_sweep_summary)

    # Mock update_task_status (sweep 全失败 fallback 用, 这里不到)
    monkeypatch.setattr(sweep_mod, "update_task_status", lambda *a, **kw: True)

    result = _run(run_sweep(
        user_id=6, script_id="mas_v1", stock_code="000001.SZ",
        param_grid={"fast": [3, 5, 7, 10], "slow": [20]},
        metric="sharpe",
        backtest_start_date="20260101",
        backtest_end_date="20260110",
        concurrency=2,
    ))

    assert result["total_runs"] == 4
    assert result["succeeded"] == 4
    assert result["failed"] == 0
    assert result["best_params"]["fast"] == 10  # 最高 sharpe
    assert result["best_metric_value"] == pytest.approx(0.5 + 10 * 0.1)

    # summary 写入校验
    assert len(captured["sweep_results"]) == 4
    # 第 1 个 (sweep_results[0]) 应该是 fast=10 (最高)
    assert captured["sweep_results"][0]["params"]["fast"] == 10


def test_run_sweep_partial_failure(monkeypatch):
    """2/4 组合 backtest 抛错 → sweep 继续, best 从成功的挑"""
    from strategy_exec.engines.backtrader import sweep as sweep_mod

    fake_bars = [{"open": 1, "close": 1.5, "stime": "20260101"}]
    monkeypatch.setattr(sweep_mod, "fetch_his_bars", AsyncMock(return_value=fake_bars))

    _task_id_counter = [2000]
    def fake_create_sweep_task(**kwargs):
        _task_id_counter[0] += 1
        return _task_id_counter[0]
    monkeypatch.setattr(sweep_mod, "create_sweep_task", fake_create_sweep_task)

    # fast=5, 10 成功; fast=3, 7 抛错
    def fake_run_backtest(**kwargs):
        params = kwargs["params"]
        if params["fast"] in (3, 7):
            raise RuntimeError(f"simulated backtest error for fast={params['fast']}")
        return {
            "pnl": 100 * params["fast"],
            "initial_cash": 100000,
            "sharpe": float(params["fast"]),
        }
    monkeypatch.setattr(sweep_mod, "run_backtest", fake_run_backtest)

    captured = {}
    def fake_update_sweep_summary(**kwargs):
        captured["sweep_results"] = kwargs["sweep_results"]
        captured["best_params"] = kwargs["best_params"]
        return True
    monkeypatch.setattr(sweep_mod, "update_sweep_summary", fake_update_sweep_summary)
    monkeypatch.setattr(sweep_mod, "update_task_status", lambda *a, **kw: True)

    result = _run(run_sweep(
        user_id=6, script_id="mas_v1", stock_code="000001.SZ",
        param_grid={"fast": [3, 5, 7, 10]},
        metric="sharpe",
        backtest_start_date="20260101",
        backtest_end_date="20260110",
        concurrency=2,
    ))

    assert result["total_runs"] == 4
    assert result["succeeded"] == 2
    assert result["failed"] == 2
    # best 来自成功的: fast=10 (sharpe=10)
    assert result["best_params"]["fast"] == 10
    assert result["best_metric_value"] == 10.0
    # sweep_results 排好序: completed 按 sharpe 降序, failed 在后
    statuses = [r["status"] for r in captured["sweep_results"]]
    # 前 2 个 completed (fast=10, 5), 后 2 个 failed
    assert statuses == ["completed", "completed", "failed", "failed"]


def test_run_sweep_all_failure_summary_marked_failed(monkeypatch):
    """全失败 → summary 标 failed, best_params=None"""
    from strategy_exec.engines.backtrader import sweep as sweep_mod

    fake_bars = [{"open": 1, "close": 1.5, "stime": "20260101"}]
    monkeypatch.setattr(sweep_mod, "fetch_his_bars", AsyncMock(return_value=fake_bars))

    _task_id_counter = [3000]
    def fake_create_sweep_task(**kwargs):
        _task_id_counter[0] += 1
        return _task_id_counter[0]
    monkeypatch.setattr(sweep_mod, "create_sweep_task", fake_create_sweep_task)

    # 全部抛错
    def fake_run_backtest(**kwargs):
        raise RuntimeError("all combos fail")

    update_status_calls = []
    def fake_update_task_status(task_id, status, **kwargs):
        update_status_calls.append((task_id, status, kwargs.get("error_msg", "")))
        return True

    summary_called = {"count": 0}
    def fake_update_sweep_summary(**kwargs):
        summary_called["count"] += 1
        return True

    monkeypatch.setattr(sweep_mod, "run_backtest", fake_run_backtest)
    monkeypatch.setattr(sweep_mod, "update_task_status", fake_update_task_status)
    monkeypatch.setattr(sweep_mod, "update_sweep_summary", fake_update_sweep_summary)

    result = _run(run_sweep(
        user_id=6, script_id="mas_v1", stock_code="000001.SZ",
        param_grid={"fast": [3, 5]},
        metric="sharpe",
        backtest_start_date="20260101",
        backtest_end_date="20260110",
        concurrency=1,
    ))

    assert result["succeeded"] == 0
    assert result["failed"] == 2
    assert result["best_params"] is None
    assert result["best_metric_value"] is None
    # 不调 update_sweep_summary (因为没成功的)
    assert summary_called["count"] == 0
    # update_task_status 至少调一次 (标 summary failed)
    assert any(s == "failed" for _, s, _ in update_status_calls)


def test_run_sweep_hard_limit_rejected(monkeypatch):
    """grid > 512 → ValueError, 不创任何 task"""
    from strategy_exec.engines.backtrader import sweep as sweep_mod

    create_called = {"count": 0}
    def fake_create_sweep_task(**kwargs):
        create_called["count"] += 1
        return 9999
    monkeypatch.setattr(sweep_mod, "create_sweep_task", fake_create_sweep_task)
    monkeypatch.setattr(sweep_mod, "fetch_his_bars", AsyncMock(return_value=[]))

    with pytest.raises(ValueError, match="硬上限"):
        _run(run_sweep(
            user_id=6, script_id="x", stock_code="000001.SZ",
            # 32 × 32 = 1024 → 超硬上限
            param_grid={"a": list(range(32)), "b": list(range(32))},
            metric="sharpe",
            backtest_start_date="20260101",
            backtest_end_date="20260110",
        ))
    assert create_called["count"] == 0


def test_run_sweep_broker_no_data_raises(monkeypatch):
    """broker 返空 bars → RuntimeError"""
    from strategy_exec.engines.backtrader import sweep as sweep_mod
    monkeypatch.setattr(sweep_mod, "fetch_his_bars", AsyncMock(return_value=[]))

    with pytest.raises(RuntimeError, match="未返回 K 线"):
        _run(run_sweep(
            user_id=6, script_id="x", stock_code="000001.SZ",
            param_grid={"fast": [5]},
            metric="sharpe",
            backtest_start_date="20260101",
            backtest_end_date="20260110",
        ))
