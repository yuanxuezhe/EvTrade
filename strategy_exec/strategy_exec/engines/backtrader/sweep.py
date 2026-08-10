"""
strategy_exec.engines.backtrader.sweep — 参数扫描引擎 (v122+, Phase 4 of `2026-08-10-strategy-params-sweep-best-live`)

REQ-SE-008: 一次提交多组参数组合的回测, 按指定指标 (sharpe/total_return/calmar) 排序挑 best.

📌 流程:
    1. iter_param_grid(param_grid) → 笛卡尔积 (单值字段不参与)
    2. validate_grid_size → 软警告 64 / 硬拒绝 512
    3. asyncio.Semaphore(concurrency) 并发跑 run_backtest
    4. 每个组合 = 独立 strategy_task row (共享 sweep_id)
    5. 失败单组合 → status='failed', 记录 error_msg, sweep 继续
    6. 全部完成后 → 1 个 summary task (sweep_id 共享, status='completed')

📌 单 run 复用:
    直接调 run_backtest — 它已支持 params + bars + schema 注入 (Phase 2 改).
    sweep 不重复实现 backtest 逻辑, 仅做并发编排 + 结果聚合.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
import uuid
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional

from sqlalchemy import text

from strategy_exec.data_access import (
    create_sweep_task, update_sweep_summary,
    update_task_status, get_session,
)
from strategy_exec.engines.backtrader.backtest import run_backtest
from strategy_exec.market_data.hq_history import fetch_his_bars

log = logging.getLogger(__name__)


# ──── 常量 ────

# 笛卡尔积大小约束 (软警告前端, 硬拒绝 API)
SWEEP_SOFT_WARN = 64   # 超过仅 log warning
SWEEP_HARD_LIMIT = 512  # 超过直接 raise

# 指标名白名单
ALLOWED_METRICS = ("sharpe", "total_return", "calmar")


# ──── 纯函数 helpers (无 IO, 单测友好) ────


def iter_param_grid(param_grid: Dict[str, List[Any]]) -> Iterator[Dict[str, Any]]:
    """笛卡尔积展开.

    Args:
        param_grid: {param_name: [v1, v2, ...]}

    Yields:
        每组合 1 个 dict {param_name: value}.

    约定:
        - 字段值是空 list → 该字段跳过 (当成未配置)
        - 字段值是 1 个元素 list → 该字段**不参与**笛卡尔积 (固定值)
        - 至少需要 1 个字段含 ≥2 元素, 否则只产出 1 个组合
    """
    if not param_grid:
        return iter([{}])

    # 过滤空 list
    active = {k: v for k, v in param_grid.items() if v}
    if not active:
        return iter([{}])

    # 单值字段: 不参与笛卡尔积 (保留在每组合里)
    fixed = {k: v[0] for k, v in active.items() if len(v) == 1}
    sweep_keys = {k: v for k, v in active.items() if len(v) >= 2}

    if not sweep_keys:
        # 全是单值, 只产 1 个组合 (即 fixed 的合并)
        return iter([dict(fixed)])

    # 笛卡尔积
    keys = list(sweep_keys.keys())
    value_lists = [sweep_keys[k] for k in keys]
    return (
        dict(fixed, **dict(zip(keys, combo)))
        for combo in itertools.product(*value_lists)
    )


def count_grid_size(param_grid: Dict[str, List[Any]]) -> int:
    """算 param_grid 总组合数 (用于 validate, 不迭代全部)"""
    if not param_grid:
        return 1
    active = [v for v in param_grid.values() if v and len(v) >= 2]
    if not active:
        return 1
    size = 1
    for v in active:
        size *= len(v)
    return size


def validate_grid_size(grid_size: int, soft_warn: int = SWEEP_SOFT_WARN,
                       hard_limit: int = SWEEP_HARD_LIMIT) -> None:
    """校验 grid 大小.

    Raises:
        ValueError: grid_size > hard_limit (硬拒绝)
    Side effect:
        grid_size > soft_warn → log warning (软警告, 不阻断)
    """
    if grid_size > hard_limit:
        raise ValueError(
            f"sweep 组合数 {grid_size} 超过硬上限 {hard_limit}, "
            f"请减少参数扫描范围或拆多次跑"
        )
    if grid_size > soft_warn:
        log.warning("[sweep] 组合数 %d > 软警告阈值 %d, 跑起来会比较慢",
                    grid_size, soft_warn)


def validate_metric(metric: str) -> None:
    if metric not in ALLOWED_METRICS:
        raise ValueError(
            f"metric 必须是 {ALLOWED_METRICS} 之一, 收到: {metric!r}"
        )


def extract_metric_value(backtest_result: Dict[str, Any], metric: str) -> Optional[float]:
    """从单 run 的 backtest_result 提取指定 metric 值.

    Args:
        backtest_result: run_backtest 返回的 dict
        metric: 'sharpe' / 'total_return' / 'calmar'

    Returns:
        metric 数值, 无则 None
    """
    if not backtest_result or not isinstance(backtest_result, dict):
        return None
    if metric == "sharpe":
        v = backtest_result.get("sharpe")
        return float(v) if v is not None else None
    if metric == "total_return":
        pnl = backtest_result.get("pnl")
        cash = backtest_result.get("initial_cash") or 100000.0
        if pnl is None:
            return None
        return float(pnl) / float(cash)
    if metric == "calmar":
        # calmar = total_return / max_drawdown, 无 max_drawdown analyzer → None
        total_ret = extract_metric_value(backtest_result, "total_return")
        max_dd = backtest_result.get("max_drawdown")
        if total_ret is None or max_dd is None or float(max_dd) == 0.0:
            return None
        return total_ret / abs(float(max_dd))
    return None


# ──── 主流程 ────


def generate_sweep_id() -> str:
    """uuid4 hex 截 32 位 (DB sweep_id VARCHAR(32))"""
    return uuid.uuid4().hex[:32]


async def run_sweep(
    user_id: int,
    script_id: str,
    stock_code: str,
    param_grid: Dict[str, List[Any]],
    metric: str,
    backtest_start_date: str,
    backtest_end_date: str,
    *,
    period: str = "1d",
    concurrency: int = 2,
    sweep_id: Optional[str] = None,
    select_top_n: int = 1,
    description: Optional[str] = None,
) -> Dict[str, Any]:
    """跑一次 sweep: 笛卡尔积展开 → 并发跑 backtest → 写 summary task.

    Args:
        user_id / script_id / stock_code: 任务归属
        param_grid: {param_name: [v1, v2, ...]}
        metric: 'sharpe' / 'total_return' / 'calmar'
        backtest_start_date / backtest_end_date: YYYYMMDD
        period: K 线周期 (1d / 1m / ...)
        concurrency: 同时跑的 backtest 数 (默认 2, env STRATEGY_SWEEP_CONCURRENCY 可覆盖)
        sweep_id: 自定义 sweep_id (默认 uuid4 hex[:32])
        select_top_n: 取 top N 组合写 best_params (默认 1)
        description: 任务描述

    Returns:
        {
            'sweep_id': str,
            'total_runs': int,
            'summary_task_id': int,
            'best_params': dict,
            'best_metric_value': float | None,
            'succeeded': int,
            'failed': int,
        }

    Raises:
        ValueError: grid > SWEEP_HARD_LIMIT / metric 不合法
        RuntimeError: 拉 K 线失败 / DB 失败
    """
    validate_metric(metric)

    grid_size = count_grid_size(param_grid)
    validate_grid_size(grid_size)

    sweep_id = sweep_id or generate_sweep_id()

    log.info(
        "[sweep] start sweep_id=%s user=%d script=%s stock=%s grid=%d metric=%s concurrency=%d",
        sweep_id, user_id, script_id, stock_code, grid_size, metric, concurrency,
    )

    # ──── 1. 拉一次 K 线 (所有组合共享) ────
    try:
        bars = await fetch_his_bars(
            stock_code=stock_code,
            start_date=backtest_start_date,
            end_date=backtest_end_date,
            period=period,
        )
    except Exception as e:
        log.error("[sweep %s] fetch_his_bars failed: %s", sweep_id, e)
        raise RuntimeError(f"broker his_hq 行情拉取失败: {e}") from e

    if not bars:
        raise RuntimeError(f"broker 未返回 K 线数据 (stock={stock_code})")

    # ──── 2. 展开 grid + 预创建所有 task row ────
    combos = list(iter_param_grid(param_grid))
    sweep_total = len(combos) + 1  # +1 = summary task
    log.info("[sweep %s] generated %d combinations", sweep_id, len(combos))

    # 预创建所有组合 task (status='pending'), 这样 sweep_id 就绑好了
    combo_task_ids: List[int] = []
    for combo in combos:
        task_id = create_sweep_task(
            user_id=user_id, script_id=script_id, stock_code=stock_code,
            params=combo, sweep_id=sweep_id, sweep_metric=metric,
            sweep_total=sweep_total,
            backtest_start_date=backtest_start_date,
            backtest_end_date=backtest_end_date,
            period=period,
            description=description,
        )
        combo_task_ids.append(task_id)

    # ──── 3. 并发跑 backtest (Semaphore 控制) ────
    sem = asyncio.Semaphore(max(1, concurrency))

    async def _run_one(combo: Dict[str, Any], task_id: int) -> Dict[str, Any]:
        async with sem:
            log.info("[sweep %s] task=%d start params=%s", sweep_id, task_id, combo)
            try:
                # run_backtest 是 sync 函数 → asyncio.to_thread
                result = await asyncio.to_thread(
                    run_backtest,
                    task_id=task_id, user_id=user_id, script_id=script_id,
                    stock_code=stock_code, params=combo, bars=bars,
                    backtest_start_date=backtest_start_date,
                    backtest_end_date=backtest_end_date,
                    period=period,
                )
                metric_value = extract_metric_value(result, metric)
                log.info("[sweep %s] task=%d OK metric=%.4f", sweep_id, task_id, metric_value or 0.0)
                return {
                    "task_id": task_id,
                    "params": combo,
                    "metric_value": metric_value,
                    "status": "completed",
                    "metric": metric,
                }
            except Exception as e:
                log.warning("[sweep %s] task=%d FAILED: %s", sweep_id, task_id, e)
                return {
                    "task_id": task_id,
                    "params": combo,
                    "metric_value": None,
                    "status": "failed",
                    "error_msg": str(e)[:200],
                    "metric": metric,
                }

    results = await asyncio.gather(*(_run_one(c, tid) for c, tid in zip(combos, combo_task_ids)))

    # ──── 4. 排序 + 写 summary task ────
    # 排序: completed (按 metric_value 降序) 排前, failed 排后
    completed = [r for r in results if r["status"] == "completed" and r["metric_value"] is not None]
    failed = [r for r in results if r not in completed]
    completed.sort(key=lambda r: r["metric_value"], reverse=True)
    sorted_results = completed + failed

    best_params = completed[0]["params"] if completed else None
    best_metric_value = completed[0]["metric_value"] if completed else None

    # 创建 summary task
    summary_task_id = create_sweep_task(
        user_id=user_id, script_id=script_id, stock_code=stock_code,
        params={},  # summary 无单组 params
        sweep_id=sweep_id, sweep_metric=metric, sweep_total=sweep_total,
        backtest_start_date=backtest_start_date,
        backtest_end_date=backtest_end_date,
        period=period,
        description=description or f"Sweep summary ({len(combos)} runs, metric={metric})",
    )

    if completed:
        # 写 summary (best_params + sweep_results 排序后数组)
        update_sweep_summary(
            task_id=summary_task_id,
            sweep_results=sorted_results,
            best_params=best_params,
            best_metric_value=best_metric_value,
            metric=metric,
        )
    else:
        # 全失败 → summary 也标 failed
        update_task_status(
            summary_task_id, "failed",
            error_msg=f"sweep 全失败 ({len(failed)}/{len(combos)} 失败), 无 best_params",
        )
        log.warning("[sweep %s] all %d combos failed", sweep_id, len(combos))

    log.info(
        "[sweep %s] done: %d succeeded, %d failed, best_metric=%.4f",
        sweep_id, len(completed), len(failed), best_metric_value or 0.0,
    )

    return {
        "sweep_id": sweep_id,
        "total_runs": len(combos),
        "summary_task_id": summary_task_id,
        "best_params": best_params,
        "best_metric_value": best_metric_value,
        "succeeded": len(completed),
        "failed": len(failed),
    }


async def stream_sweep_progress(sweep_id: str) -> AsyncIterator[Dict[str, Any]]:
    """(预留) 流式 yield sweep 进度 — 给前端 SSE / WS 订阅.

    当前 phase 未启用, 留接口. 实现需每个组合 update_task_progress 加 phase='sweep_running'.
    """
    # TODO: Phase 5+ 加 WS 进度推送
    if False:
        yield {}
