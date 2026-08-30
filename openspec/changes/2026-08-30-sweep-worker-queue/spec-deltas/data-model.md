# data-model delta — sweep-worker-queue

## MODIFIED: `strategy_task` 加列 `run_generation`（2026-08-30）

`strategy_task` 加 1 列 `run_generation INT NOT NULL DEFAULT 0`（migration `2026-08-30-add-strategy-task-run-generation.py`，幂等 INFORMATION_SCHEMA 检测）。

- **语义**：回测任务的**代际 + 重跑计数器**，供 worker 队列的堵塞自愈用（详见 [`strategy-exec/spec.md`](../strategy-exec/spec.md)「worker 队列堵塞自愈 + 代际隔离」）
  - worker 原子领取（claim）某 queued task 时 `run_generation = run_generation + 1`，worker 记下本次代际
  - 该 task 的 progress 写（`patched_next`）/ 终态写（result / status）都带 `WHERE run_generation = 本次代际`
  - **孤儿线程**（被复位重跑后仍后台运行的旧 `to_thread` 线程）晚到的写因代际不匹配 → no-op，不覆盖新那次的结果/心跳
  - `run_generation > backtest_max_retries`（默认 3）→ 标 `status='failed'`，防无限重跑
- **存量数据**：现有 task 行 `run_generation=0`，无影响（只在 worker 领取时才 +1）
- **索引**：不新增索引（`run_generation` 不参与查询过滤，领取走 `status`/`batch_no` 现有索引）

> 演进历史补一行（Tables Overview 演进段）：
> - **2026-08-30 sweep-worker-queue**：`strategy_task` 加 `run_generation INT NOT NULL DEFAULT 0`（代际 + 重跑计数，worker 队列堵塞自愈的代际隔离；migration `2026-08-30-add-strategy-task-run-generation.py`）。详见 [`strategy-exec/spec.md`](../strategy-exec/spec.md)
