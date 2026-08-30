"""
test_run_batch_dispatch.py — /internal/run-batch 派发单测 (change 2026-08-30-sweep-worker-queue)

覆盖 internal._dispatch_batch (worker 池派发入口):
  - 返 get_batch_tasks 的总数 (前端 total_runs 展示)
  - 调 _connect_publisher + create_task(run_worker_pool, 正确参数)
策略: mock get_batch_tasks / _connect_publisher / asyncio.create_task (不真跑池)。
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import strategy_exec.api.internal as internal


def test_dispatch_batch_returns_total_and_spawns_worker_pool():
    with patch("strategy_exec.data_access.get_batch_tasks",
               return_value=[{"id": 1}, {"id": 2}, {"id": 3}]) as mock_tasks, \
         patch.object(internal, "_connect_publisher", new=AsyncMock()), \
         patch("strategy_exec.engines.backtrader.worker.run_worker_pool",
               new=AsyncMock()) as mock_pool, \
         patch("asyncio.create_task", new=MagicMock(return_value=MagicMock())) as mock_create:
        total = asyncio.run(internal._dispatch_batch(
            strategy_id=100, batch_no=5, user_id=1, script_id="s1",
            stock_code="159992.SZ", backtest_start_date="20260101",
            backtest_end_date="20260131", metric="sharpe", concurrency=2, period="1d",
        ))
    assert total == 3
    assert mock_tasks.call_count >= 1
    # create_task 被调 (起 worker 池后台任务)
    assert mock_create.call_count == 1
    # run_worker_pool 的协程被传给 create_task (验证 wiring)
    coro = mock_create.call_args[0][0]
    # 跑一下这个协程, 验证它确实调用 run_worker_pool
    asyncio.run(coro)
    assert mock_pool.call_count == 1
    # 参数透传
    assert mock_pool.call_args.kwargs["strategy_id"] == 100
    assert mock_pool.call_args.kwargs["batch_no"] == 5
    assert mock_pool.call_args.kwargs["concurrency"] == 2
    assert mock_pool.call_args.kwargs["metric"] == "sharpe"


def test_dispatch_batch_empty_batch_zero_runs():
    with patch("strategy_exec.data_access.get_batch_tasks", return_value=[]) , \
         patch.object(internal, "_connect_publisher", new=AsyncMock()), \
         patch("strategy_exec.engines.backtrader.worker.run_worker_pool", new=AsyncMock()), \
         patch("asyncio.create_task", new=MagicMock(return_value=MagicMock())):
        total = asyncio.run(internal._dispatch_batch(
            strategy_id=100, batch_no=5, user_id=1, script_id="s1",
            stock_code="X", backtest_start_date="20260101",
            backtest_end_date="20260131", metric="sharpe", concurrency=2, period="1d",
        ))
    assert total == 0
