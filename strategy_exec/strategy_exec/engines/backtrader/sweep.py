"""
strategy_exec.engines.backtrader.sweep — 参数扫描引擎 (v123, strategy-batch-task-model)

v123 重写: EvTrade 在调用 strategy_exec 前已为批次预建好 task 行
(strategy_id + batch_no + params 已落库). strategy_exec 只负责:

  1. param_ranges 类型化展开组合 → 校验笛卡尔积大小 (软警告 64 / 硬拒绝 512)
  2. 按 (strategy_id, batch_no) 读批次内已有 task (params 取自 DB, 不自建)
  3. asyncio.Semaphore(concurrency) 并发跑 run_backtest
  4. 失败单 task → status='failed', 其余继续 (容错, 不中断批次)
  5. 批次完成 → 按 metric 取 finished top1 → UPDATE strategy SET best_params
     (全部失败不写)

不再自建 task / summary task / sweep_id; backtest_result 不再有 sweep_results 顶层冗余.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
from typing import Any, Dict, Iterator, List, Optional

from strategy_exec.data_access import (
    get_batch_tasks, update_strategy_best_params,
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


def _expand_values(spec: Dict[str, Any]) -> List[Any]:
    """按 spec.type 展开一个参数的取值序列.

    Args:
        spec: {type: int|float|choice|string, ...}
          - int:    {start, end, step} 含端点, 步进取整
          - float:  {start, end, step} 含端点, 末位钳到 end 防浮点漂移
          - choice: {values: [...]} 原样取值
          - string: {value} 固定 (返回单元素)

    Returns:
        list of 参数值; 空列表 = 该参数无可用取值 (调用方应跳过)
    """
    if not spec or not isinstance(spec, dict):
        return []
    t = spec.get("type")
    if t == "int":
        start = spec.get("start")
        end = spec.get("end")
        step = spec.get("step") or 1
        if start is None or end is None or step <= 0:
            return []
        out: List[Any] = []
        v = float(start)
        while v <= float(end):
            out.append(int(round(v)))
            v += float(step)
        return out
    if t == "float":
        start = spec.get("start")
        end = spec.get("end")
        step = spec.get("step") or 1
        if start is None or end is None or step <= 0:
            return []
        out = []
        v = float(start)
        while v <= float(end):
            out.append(round(v, 10))
            v += float(step)
        # 防浮点末位差一跳: 保证最后一个值正好是 end
        if out and out[-1] != float(end):
            out.append(float(end))
        return out
    if t == "choice":
        return [v for v in (spec.get("values") or []) if v is not None and v != ""]
    if t == "string":
        v = spec.get("value")
        return [v] if v is not None else []
    return []


def iter_param_ranges(param_ranges: Dict[str, Dict[str, Any]]) -> Iterator[Dict[str, Any]]:
    """按类型展开 param_ranges → 笛卡尔积.

    Args:
        param_ranges: {param_name: {type, start, end, step | values | value}}

    Yields:
        每组合 1 个 dict {param_name: value}.

    约定:
        - 参数展开后 1 个取值 → 该字段**不参与**笛卡尔积 (固定值)
        - 参数展开后空列表 → 跳过 (不放进任何组合, sandbox 默认兜底)
        - 至少需要 1 个字段含 ≥2 取值, 否则只产出 1 个组合 (全是固定值)
    """
    if not param_ranges:
        return iter([{}])

    fixed: Dict[str, Any] = {}
    active: Dict[str, List[Any]] = {}
    for key, spec in param_ranges.items():
        vals = _expand_values(spec)
        if not vals:
            continue  # 无可用取值 → 跳过
        if len(vals) == 1:
            fixed[key] = vals[0]
        else:
            active[key] = vals

    if not active:
        return iter([dict(fixed)])

    keys = list(active.keys())
    value_lists = [active[k] for k in keys]
    return (
        dict(fixed, **dict(zip(keys, combo)))
        for combo in itertools.product(*value_lists)
    )


def count_param_ranges(param_ranges: Dict[str, Dict[str, Any]]) -> int:
    """算 param_ranges 展开后总组合数 (用于 validate, 不迭代全部)"""
    return len(list(iter_param_ranges(param_ranges)))


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


async def run_sweep_batch(
    strategy_id: int,
    batch_no: int,
    user_id: int,
    script_id: str,
    stock_code: str,
    param_ranges: Dict[str, Dict[str, Any]],
    metric: str,
    backtest_start_date: str,
    backtest_end_date: str,
    *,
    period: str = "1d",
    concurrency: int = 2,
) -> Dict[str, Any]:
    """跑一个已预建好的扫描批次: 读批次 task → 并发 backtest → 写 strategy.best_params.

    Args:
        strategy_id: 策略主键 (best_params 回写目标)
        batch_no: 批次号 (strategy_task.batch_no, EvTrade 预生成)
        user_id / script_id / stock_code: 任务归属 (回测转发用)
        param_ranges: {param_name: {type, start, end, step | values | value}} 类型化扫描定义
        metric: 'sharpe' / 'total_return' / 'calmar'
        backtest_start_date / backtest_end_date: YYYYMMDD
        period: K 线周期 (1d / 1m / ...)
        concurrency: 同时跑的 backtest 数 (默认 2)

    Returns:
        {
            'strategy_id': int,
            'batch_no': int,
            'total_runs': int,
            'best_params': dict | None,
            'best_metric_value': float | None,
            'succeeded': int,
            'failed': int,
        }

    Raises:
        ValueError: grid > SWEEP_HARD_LIMIT / metric 不合法
        RuntimeError: 拉 K 线失败 / 批次不存在 / DB 失败
    """
    validate_metric(metric)

    combos = list(iter_param_ranges(param_ranges))
    grid_size = len(combos)
    validate_grid_size(grid_size)

    # ──── 1. 读批次内已有 task (params 已在 DB, 不自建) ────
    tasks = get_batch_tasks(strategy_id, batch_no)
    if not tasks:
        raise RuntimeError(
            f"batch 不存在: strategy_id={strategy_id} batch_no={batch_no}"
        )
    if len(tasks) != grid_size:
        log.warning(
            "[sweep strategy=%d batch=%d] DB task 数 %d != param_ranges 展开数 %d, "
            "按 DB 实际任务跑",
            strategy_id, batch_no, len(tasks), grid_size,
        )

    log.info(
        "[sweep] start strategy_id=%d batch_no=%d user=%d script=%s stock=%s "
        "runs=%d metric=%s concurrency=%d",
        strategy_id, batch_no, user_id, script_id, stock_code,
        len(tasks), metric, concurrency,
    )

    # ──── 2. 拉一次 K 线 (所有组合共享) ────
    try:
        bars = await fetch_his_bars(
            stock_code=stock_code,
            start_date=backtest_start_date,
            end_date=backtest_end_date,
            period=period,
        )
    except Exception as e:
        log.error("[sweep strategy=%d batch=%d] fetch_his_bars failed: %s",
                  strategy_id, batch_no, e)
        raise RuntimeError(f"broker his_hq 行情拉取失败: {e}") from e

    if not bars:
        raise RuntimeError(f"broker 未返回 K 线数据 (stock={stock_code})")

    # ──── 3. 并发跑 backtest (Semaphore 控制) ────
    sem = asyncio.Semaphore(max(1, concurrency))

    async def _run_one(task: Dict[str, Any]) -> Dict[str, Any]:
        task_id = task["id"]
        combo = task.get("params") or {}
        async with sem:
            log.info("[sweep strategy=%d batch=%d] task=%d start params=%s",
                     strategy_id, batch_no, task_id, combo)
            try:
                # run_backtest 是 sync 函数 → asyncio.to_thread
                result = await asyncio.to_thread(
                    run_backtest,
                    task_id=task_id, user_id=user_id, script_id=script_id,
                    stock_code=stock_code, params=combo, bars=bars,
                    backtest_start_date=backtest_start_date,
                    backtest_end_date=backtest_end_date,
                    period=period,
                    strategy_id=strategy_id,   # 单组合回写由批次统一处理
                    update_strategy_best=False,
                )
                metric_value = extract_metric_value(result, metric)
                log.info("[sweep strategy=%d batch=%d] task=%d OK metric=%.4f",
                         strategy_id, batch_no, task_id, metric_value or 0.0)
                return {
                    "task_id": task_id,
                    "params": combo,
                    "metric_value": metric_value,
                    "status": "completed",
                    "error_msg": None,
                }
            except Exception as e:
                log.warning("[sweep strategy=%d batch=%d] task=%d FAILED: %s",
                            strategy_id, batch_no, task_id, e)
                return {
                    "task_id": task_id,
                    "params": combo,
                    "metric_value": None,
                    "status": "failed",
                    "error_msg": str(e)[:200],
                }

    results = await asyncio.gather(*(_run_one(t) for t in tasks))

    # ──── 4. 排序 + 回写 strategy.best_params ────
    # 排序: completed (按 metric_value 降序) 排前, failed 排后
    completed = [r for r in results if r["status"] == "completed" and r["metric_value"] is not None]
    failed = [r for r in results if r not in completed]
    completed.sort(key=lambda r: r["metric_value"], reverse=True)

    best_params = completed[0]["params"] if completed else None
    best_metric_value = completed[0]["metric_value"] if completed else None

    if best_params is not None:
        # 有完成的组合 → 写 strategy.best_params (全部失败不写)
        update_strategy_best_params(strategy_id, best_params)
    else:
        log.warning(
            "[sweep strategy=%d batch=%d] 全部 %d 组合失败, 不写 best_params",
            strategy_id, batch_no, len(tasks),
        )

    log.info(
        "[sweep strategy=%d batch=%d] done: %d succeeded, %d failed, best_metric=%.4f",
        strategy_id, batch_no, len(completed), len(failed), best_metric_value or 0.0,
    )

    return {
        "strategy_id": strategy_id,
        "batch_no": batch_no,
        "total_runs": len(tasks),
        "best_params": best_params,
        "best_metric_value": best_metric_value,
        "succeeded": len(completed),
        "failed": len(failed),
    }
