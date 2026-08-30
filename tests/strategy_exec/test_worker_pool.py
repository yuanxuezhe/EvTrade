"""
test_worker_pool.py — 回测 worker 队列单测 (change 2026-08-30-sweep-worker-queue)

覆盖 (mock DB/IO/run_backtest, 不打真实 DB/broker):
  run_worker_pool:
    - 正常: N worker FIFO 领取 → 全 finished → finalize 写 best_params (top1 by metric)
    - 批次不存在 → RuntimeError
    - K 线拉取失败 → RuntimeError
    - 超时自愈: 某 task timeout → requeue (回 queued) → 被再次领取重跑 → 最终 finished
    - 超重重跑上限: 连续 timeout 达 max_retries → 标 failed
  _worker:
    - 领取 → 跑 finished → 写 metric → 领下一个 → 队列空退出
  _finalize_batch:
    - 有 finished → top1 回写 best_params
    - 全失败 → 不写 best_params

策略: patch worker 命名空间内的 get_settings / claim_next_queued / requeue_or_fail_on_timeout /
get_batch_tasks / fetch_his_bars / run_backtest (async) / update_task_metric / update_strategy_best_params。
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import strategy_exec.engines.backtrader.worker as W


def _settings(timeout_s=600, max_retries=3, poll=0.01):
    return SimpleNamespace(
        backtest_task_timeout_seconds=timeout_s,
        backtest_max_retries=max_retries,
        worker_poll_interval_seconds=poll,
    )


def _bars():
    return [{"stime": "20260101093000", "close": 10.0}]


def test_run_worker_pool_happy_path(monkeypatch):
    """3 个 queued task, 2 worker → 全 finished → finalize top1 写 best_params"""
    monkeypatch.setattr(W, "get_settings", lambda: _settings())

    # claim: 按序领 3 个 (id 1,2,3), 每次 gen 递增; 领完返 None
    claim_seq = [
        {"task_id": 1, "run_generation": 1, "params": {"a": 1}},
        {"task_id": 2, "run_generation": 1, "params": {"a": 2}},
        {"task_id": 3, "run_generation": 1, "params": {"a": 3}},
        None, None, None,  # 各 worker 收尾判空 (多 None 兜住)
    ]
    claim_it = iter(claim_seq)
    monkeypatch.setattr(W, "claim_next_queued", lambda **kw: next(claim_it, None))
    monkeypatch.setattr(W, "get_batch_tasks", lambda sid, bn: [
        {"id": 1, "status": "finished", "backtest_metric_value": 0.5, "params": {"a": 1}},
        {"id": 2, "status": "finished", "backtest_metric_value": 1.5, "params": {"a": 2}},
        {"id": 3, "status": "finished", "backtest_metric_value": 0.8, "params": {"a": 3}},
    ])
    monkeypatch.setattr(W, "fetch_his_bars", AsyncMock(return_value=_bars()))

    # run_backtest (to_thread 里调) → 各返 metric: id1=0.5 id2=1.5 id3=0.8
    def _fake_run_backtest(**kw):
        return {"sharpe": {"1": 0.5, "2": 1.5, "3": 0.8}.get(str(kw["task_id"]))}
    monkeypatch.setattr(W, "run_backtest", _fake_run_backtest)
    monkeypatch.setattr(W, "extract_metric_value", lambda r, m: r.get("sharpe"))
    monkeypatch.setattr(W, "update_task_metric", lambda **kw: True)
    best_calls = []
    monkeypatch.setattr(W, "update_strategy_best_params",
                        lambda sid, bp: best_calls.append(bp))

    result = asyncio.run(W.run_worker_pool(
        strategy_id=100, batch_no=5, user_id=1, script_id="s1",
        stock_code="159992.SZ", backtest_start_date="20260101",
        backtest_end_date="20260131", period="1d", concurrency=2, metric="sharpe",
    ))

    assert result["succeeded"] == 3
    assert result["failed"] == 0
    # top1 = id2 (metric 1.5) → params {a:2}
    assert best_calls == [{"a": 2}]
    assert result["best_metric_value"] == 1.5


def test_run_worker_pool_batch_not_found(monkeypatch):
    monkeypatch.setattr(W, "get_settings", lambda: _settings())
    monkeypatch.setattr(W, "get_batch_tasks", lambda sid, bn: [])
    monkeypatch.setattr(W, "fetch_his_bars", AsyncMock(return_value=_bars()))
    import pytest
    with pytest.raises(RuntimeError, match="batch 不存在"):
        asyncio.run(W.run_worker_pool(
            strategy_id=100, batch_no=99, user_id=1, script_id="s1",
            stock_code="X", backtest_start_date="20260101",
            backtest_end_date="20260131",
        ))


def test_run_worker_pool_fetch_bars_failed(monkeypatch):
    monkeypatch.setattr(W, "get_settings", lambda: _settings())
    monkeypatch.setattr(W, "get_batch_tasks", lambda sid, bn: [{"id": 1, "status": "queued"}])
    monkeypatch.setattr(W, "fetch_his_bars", AsyncMock(side_effect=RuntimeError("broker down")))
    import pytest
    with pytest.raises(RuntimeError, match="行情拉取失败"):
        asyncio.run(W.run_worker_pool(
            strategy_id=100, batch_no=5, user_id=1, script_id="s1",
            stock_code="X", backtest_start_date="20260101",
            backtest_end_date="20260131",
        ))


def test_worker_timeout_self_heal_requeue(monkeypatch):
    """task 1 首次 timeout → requeue 返 'requeued' → 再次领取(重跑) → finished"""
    monkeypatch.setattr(W, "get_settings", lambda: _settings(max_retries=3))
    claim_seq = [
        {"task_id": 1, "run_generation": 1, "params": {"a": 1}},   # 第1次领 task1 (将 timeout)
        {"task_id": 1, "run_generation": 2, "params": {"a": 1}},   # 复位后重领 task1
        None, None,
    ]
    claim_it = iter(claim_seq)
    monkeypatch.setattr(W, "claim_next_queued", lambda **kw: next(claim_it, None))
    monkeypatch.setattr(W, "get_batch_tasks", lambda sid, bn: [
        {"id": 1, "status": "finished", "backtest_metric_value": 1.0, "params": {"a": 1}},
    ])
    monkeypatch.setattr(W, "fetch_his_bars", AsyncMock(return_value=_bars()))

    # 第1次 run timeout, 第2次 (gen=2) 成功
    run_state = {"n": 0}
    def _fake_run_backtest(**kw):
        run_state["n"] += 1
        if kw["run_generation"] == 1:
            raise asyncio.TimeoutError()  # 模拟 to_thread 超时 (wait_for 转 TimeoutError)
        return {"sharpe": 1.0}
    monkeypatch.setattr(W, "run_backtest", _fake_run_backtest)
    monkeypatch.setattr(W, "extract_metric_value", lambda r, m: r.get("sharpe"))

    requeue_calls = []
    monkeypatch.setattr(W, "requeue_or_fail_on_timeout",
                        lambda **kw: requeue_calls.append(kw) or "requeued")
    monkeypatch.setattr(W, "update_task_metric", lambda **kw: True)
    best_calls = []
    monkeypatch.setattr(W, "update_strategy_best_params", lambda sid, bp: best_calls.append(bp))

    result = asyncio.run(W.run_worker_pool(
        strategy_id=100, batch_no=5, user_id=1, script_id="s1",
        stock_code="X", backtest_start_date="20260101",
        backtest_end_date="20260131", concurrency=1, metric="sharpe",
    ))

    # 复位被调用 1 次 (首次 timeout)
    assert len(requeue_calls) == 1
    assert requeue_calls[0]["run_generation"] == 1
    # 最终 task1 finished (重跑成功)
    assert result["succeeded"] == 1
    assert result["failed"] == 0


def test_worker_timeout_exceeds_max_retries(monkeypatch):
    """task 1 连续 timeout 达 max_retries → requeue 返 'failed' → 批次 failed"""
    monkeypatch.setattr(W, "get_settings", lambda: _settings(max_retries=2))
    # gen_cap=2 → 只领 gen<2 的行; task1 已 gen=1 → 领到; 超时复位 gen=1 但 max_retries=2 内
    # 再领 gen=2? gen_cap=2 排除 gen>=2 → 领不到 → 队列空退出 (task1 停 gen=2 running? 不, 复位回 queued gen 不变)
    # 简化: 每次 timeout 都 requeue, 第 max_retries 次返 'failed'
    claim_seq = [
        {"task_id": 1, "run_generation": 1, "params": {"a": 1}},
        {"task_id": 1, "run_generation": 2, "params": {"a": 1}},
        None, None,
    ]
    claim_it = iter(claim_seq)
    monkeypatch.setattr(W, "claim_next_queued", lambda **kw: next(claim_it, None))
    monkeypatch.setattr(W, "get_batch_tasks", lambda sid, bn: [
        {"id": 1, "status": "failed", "backtest_metric_value": None, "params": {"a": 1}},
    ])
    monkeypatch.setattr(W, "fetch_his_bars", AsyncMock(return_value=_bars()))
    monkeypatch.setattr(W, "run_backtest", lambda **kw: (_ for _ in ()).throw(asyncio.TimeoutError()))
    monkeypatch.setattr(W, "extract_metric_value", lambda r, m: None)

    requeue_results = iter(["requeued", "failed"])
    monkeypatch.setattr(W, "requeue_or_fail_on_timeout",
                        lambda **kw: next(requeue_results))
    monkeypatch.setattr(W, "update_task_metric", lambda **kw: True)
    best_calls = []
    monkeypatch.setattr(W, "update_strategy_best_params", lambda sid, bp: best_calls.append(bp))

    result = asyncio.run(W.run_worker_pool(
        strategy_id=100, batch_no=5, user_id=1, script_id="s1",
        stock_code="X", backtest_start_date="20260101",
        backtest_end_date="20260131", concurrency=1, metric="sharpe",
    ))

    # 全 failed → 不写 best_params
    assert result["failed"] == 1
    assert result["succeeded"] == 0
    assert best_calls == []


def test_finalize_batch_no_finished_no_best(monkeypatch):
    """全失败 → finalize 不写 best_params"""
    monkeypatch.setattr(W, "get_batch_tasks", lambda sid, bn: [
        {"id": 1, "status": "failed", "backtest_metric_value": None, "params": {"a": 1}},
        {"id": 2, "status": "failed", "backtest_metric_value": None, "params": {"a": 2}},
    ])
    best_calls = []
    monkeypatch.setattr(W, "update_strategy_best_params", lambda sid, bp: best_calls.append(bp))
    result = W._finalize_batch(strategy_id=100, batch_no=5, metric="sharpe")
    assert result["best_params"] is None
    assert best_calls == []
