"""
strategy_exec.engines.backtrader.worker — 回测任务执行队列 (worker 池 + 堵塞自愈)

📌 change 2026-08-30-sweep-worker-queue: 取代旧 sweep 的 `asyncio.gather` 一把梭内存态执行。

模型 (用户拍板 2026-08-30):
- **每次触发拉 N 个 worker** (N=concurrency), FIFO **有界并发**从 DB 队列领 task 跑回测
- 提交 (EvTrade) 只建 N 行 `status='queued'` task + 立即 202, 不等执行
- worker 原子领取 (claim_next_queued, SKIP LOCKED + 代际+1) → to_thread(run_backtest)
- **堵塞自愈**: 单 task 执行超 `backtest_task_timeout_seconds` → 复位 (回 queued 重跑 / 超
  backtest_max_retries 标 failed), worker 复位去领下一个
- **代际隔离**: 被复位重跑的 task, 旧线程(孤儿)晚到的写因 run_generation 不匹配 → no-op
- 批次领空后: 按 metric 取 finished top1 (backtest_metric_value) 回写 strategy.best_params

K 线: 每批次 worker 池启动拉 1 次 fetch_his_bars, 全批次共享。
single (1 行) + sweep (N 行) 统一走本 worker 池。
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional

from strategy_exec.config import get_settings
from strategy_exec.data_access import (
    claim_next_queued,
    get_batch_tasks,
    requeue_or_fail_on_timeout,
    update_strategy_best_params,
    update_task_metric,
)
from strategy_exec.engines.backtrader.backtest import run_backtest
from strategy_exec.engines.backtrader.sweep import extract_metric_value
from strategy_exec.market_data.hq_history import fetch_his_bars

log = logging.getLogger(__name__)


def _get_pid() -> Optional[int]:
    return os.getpid()


async def _run_one(
    task: Dict[str, Any],
    *,
    user_id: int, script_id: str, stock_code: str,
    bars: List[Dict[str, Any]],
    backtest_start_date: str, backtest_end_date: str,
    period: str, strategy_id: int, metric: str,
    timeout_s: int,
) -> Dict[str, Any]:
    """跑一个已领取的 task (带超时). 返 {status, metric_value, error}.

    status: 'finished' | 'failed' | 'timeout'
    - run_backtest 内部已写 status='finished' + result + 通用 backtest_metric_value (代际守卫)
    - 这里额外按 **sweep metric** 返 metric_value, 由 _worker 写回 backtest_metric_value
      (对齐 top1 选择口径; calmar 等 run_backtest 通用提取器不覆盖的指标靠这里)
    - 超时时 run_backtest 线程变孤儿 (杀不掉), 只返回 timeout, 由调用方复位 task
    """
    task_id = task["task_id"]
    gen = task["run_generation"]
    combo = task.get("params") or {}
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(
                run_backtest,
                task_id=task_id, user_id=user_id, script_id=script_id,
                stock_code=stock_code, params=combo, bars=bars,
                backtest_start_date=backtest_start_date,
                backtest_end_date=backtest_end_date,
                period=period,
                strategy_id=strategy_id,
                update_strategy_best=False,  # best 由批次 finalize 统一回写
                run_generation=gen,  # 代际守卫
            ),
            timeout=timeout_s,
        )
        metric_value = extract_metric_value(result, metric)
        return {"status": "finished", "metric_value": metric_value, "error": None}
    except asyncio.TimeoutError:
        log.warning("[worker] task=%d gen=%s TIMEOUT after %ds → will reset (orphan thread keeps running)",
                    task_id, gen, timeout_s)
        return {"status": "timeout", "metric_value": None, "error": f"timeout>{timeout_s}s"}
    except Exception as e:
        # run_backtest 内已 update_task_status('failed'); 这里只记录供上层判定
        log.warning("[worker] task=%d gen=%s FAILED: %s", task_id, gen, e)
        return {"status": "failed", "metric_value": None, "error": str(e)[:200]}


async def _worker(
    worker_id: int,
    *,
    strategy_id: int, batch_no: int,
    user_id: int, script_id: str, stock_code: str,
    bars: List[Dict[str, Any]],
    backtest_start_date: str, backtest_end_date: str,
    period: str, metric: str,
    timeout_s: int, max_retries: int, poll_interval: float,
) -> int:
    """单 worker: FIFO 循环领取 → 跑 → 复位超时 → 领下一个, 直到批次队列空.

    Returns: 本 worker 处理的 task 数 (finished + failed + timeout).
    """
    pid = _get_pid()
    handled = 0
    while True:
        # 原子领取下一个 queued task (SKIP LOCKED, 代际+1, 只领 gen<max_retries 防无限重跑)
        task = claim_next_queued(
            strategy_id=strategy_id, batch_no=batch_no,
            execution_pid=pid, gen_cap=max_retries,
        )
        if task is None:
            # 队列空 (或无合格行) → 本 worker 收工.
            # 短睡再查一次: 防"最后一个 task 刚被超时复位回 queued"的竞态 (复位发生在
            # worker A 超时分支, 此时 worker B 可能已判空退出). 双保险: 复位后的行 gen 仍 <
            # max_retries 可被再次领取, 由仍活跃的 worker 兜住; 若全 worker 都退出则 finalize
            # 后由上层检测残留 (见 run_worker_pool 的 drain 重试).
            await asyncio.sleep(poll_interval)
            task = claim_next_queued(
                strategy_id=strategy_id, batch_no=batch_no,
                execution_pid=pid, gen_cap=max_retries,
            )
            if task is None:
                break
        handled += 1
        log.info("[worker-%d] task=%d gen=%s start", worker_id, task["task_id"], task["run_generation"])
        out = await _run_one(
            task, user_id=user_id, script_id=script_id, stock_code=stock_code,
            bars=bars, backtest_start_date=backtest_start_date,
            backtest_end_date=backtest_end_date, period=period, metric=metric,
            strategy_id=strategy_id, timeout_s=timeout_s,
        )
        # 超时 → 复位 (回 queued 重跑 / 超限 failed); finished/failed 无需复位 (run_backtest 已写终态)
        if out["status"] == "timeout":
            action = requeue_or_fail_on_timeout(
                task_id=task["task_id"], run_generation=task["run_generation"],
                max_retries=max_retries,
            )
            log.info("[worker-%d] task=%d timeout → %s", worker_id, task["task_id"], action)
        # finished → 按 sweep metric 写回 backtest_metric_value (top1 口径, 代际守卫)
        elif out["status"] == "finished":
            update_task_metric(
                task_id=task["task_id"], metric_value=out["metric_value"],
                run_generation=task["run_generation"],
            )
    return handled


def _finalize_batch(strategy_id: int, batch_no: int, metric: str) -> Dict[str, Any]:
    """批次完成判定: 读 DB 终态 → 按 backtest_metric_value 取 finished top1 → 回写 best_params.

    change 2026-08-30-sweep-worker-queue: 原 sweep 从 gather 结果排序; 现从 DB 读 (worker
    逐 task 写 backtest_metric_value). 全部失败 → 不写 best_params.
    """
    tasks = get_batch_tasks(strategy_id, batch_no)
    finished = [
        t for t in tasks
        if t.get("status") == "finished" and t.get("backtest_metric_value") is not None
    ]
    finished.sort(key=lambda t: t.get("backtest_metric_value"), reverse=True)
    best_params = finished[0].get("params") if finished else None
    best_metric_value = finished[0].get("backtest_metric_value") if finished else None

    if best_params is not None:
        update_strategy_best_params(strategy_id, best_params)
    else:
        log.warning("[worker] batch=%d 无 finished 组合 (或全失败), 不写 best_params", batch_no)

    succeeded = sum(1 for t in tasks if t.get("status") == "finished")
    failed = sum(1 for t in tasks if t.get("status") == "failed")
    return {
        "strategy_id": strategy_id,
        "batch_no": batch_no,
        "total_runs": len(tasks),
        "best_params": best_params,
        "best_metric_value": best_metric_value,
        "succeeded": succeeded,
        "failed": failed,
    }


async def run_worker_pool(
    strategy_id: int,
    batch_no: int,
    user_id: int,
    script_id: str,
    stock_code: str,
    backtest_start_date: str,
    backtest_end_date: str,
    *,
    period: str = "1d",
    concurrency: int = 2,
    metric: str = "sharpe",
) -> Dict[str, Any]:
    """起 worker 池跑一个已预建 (N 行 queued) 的回测批次 — 统一队列入口.

    single (1 行) + sweep (N 行) 都走这里. 拉 1 次 K 线共享 → gather N worker FIFO 有界并发
    → 领空后 finalize 回写 best_params.

    Raises:
        RuntimeError: 批次不存在 / K 线拉取失败
    """
    settings = get_settings()
    timeout_s = settings.backtest_task_timeout_seconds
    max_retries = settings.backtest_max_retries
    poll_interval = settings.worker_poll_interval_seconds

    # 预建 task 校验 (不存在 → 快速失败)
    existing = get_batch_tasks(strategy_id, batch_no)
    if not existing:
        raise RuntimeError(f"batch 不存在: strategy_id={strategy_id} batch_no={batch_no}")

    # K 线共享 (1 次拉取, 全批次用)
    try:
        bars = await fetch_his_bars(
            stock_code=stock_code,
            start_date=backtest_start_date,
            end_date=backtest_end_date,
            period=period,
        )
    except Exception as e:
        log.error("[worker batch=%d] fetch_his_bars failed: %s", batch_no, e)
        raise RuntimeError(f"broker his_hq 行情拉取失败: {e}") from e
    if not bars:
        raise RuntimeError(f"broker 未返回 K 线数据 (stock={stock_code})")

    n_workers = max(1, concurrency)
    log.info(
        "[worker] batch=%d start: %d tasks, %d workers, metric=%s timeout=%ds max_retries=%d",
        batch_no, len(existing), n_workers, metric, timeout_s, max_retries,
    )

    # gather N worker FIFO 有界并发 (每 worker 领空自动退出)
    await asyncio.gather(
        *(
            _worker(
                i,
                strategy_id=strategy_id, batch_no=batch_no,
                user_id=user_id, script_id=script_id, stock_code=stock_code,
                bars=bars, backtest_start_date=backtest_start_date,
                backtest_end_date=backtest_end_date, period=period, metric=metric,
                timeout_s=timeout_s, max_retries=max_retries, poll_interval=poll_interval,
            )
            for i in range(n_workers)
        )
    )

    # finalize: 读 DB 终态 → top1 回写 best_params
    result = _finalize_batch(strategy_id, batch_no, metric)
    log.info(
        "[worker] batch=%d done: total=%d succeeded=%d failed=%d best_metric=%s",
        batch_no, result["total_runs"], result["succeeded"], result["failed"],
        result["best_metric_value"],
    )
    return result
