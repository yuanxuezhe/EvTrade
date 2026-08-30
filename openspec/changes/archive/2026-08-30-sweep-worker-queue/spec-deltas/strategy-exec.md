# strategy-exec delta — sweep-worker-queue

## MODIFIED: REQ-SE-008 (参数扫描 sweep backtest) — 执行模型改为 worker 队列

**原行为**：`/internal/run-sweep-task` 起一个 `asyncio.create_task` 内存对象，`asyncio.gather(*(_run_one(t) for t in tasks))` 一把梭并发跑完整批（Semaphore 控制）。进程崩/重启整批丢失；单任务卡死永久 `running`。

**新行为**：执行统一走 **worker 队列**（`strategy_exec/engines/backtrader/worker.py`）：
- 提交（`/internal/run-batch`）只把批次 N 行 task 置 `status='queued'`（EvTrade 预建时已完成）→ 立即 202 + 起 worker 池
- **每次触发拉 N 个 worker**（N=`concurrency`，默认 2），`asyncio.gather(*[_worker() for _ in range(N)])`
- **worker FIFO 有界并发**：循环 `claim_next_queued` 原子领取（`SKIP LOCKED` + 乐观 UPDATE `WHERE status='queued' AND execution_pid IS NULL`，`rowcount>0` 才算领到，防多 worker/多实例抢同一 task）→ `to_thread(run_backtest, run_generation=本次代际)` → 领下一个，直到批次队列空
- **K 线共享**：worker 池启动拉 1 次 `fetch_his_bars`，全批次共用
- **批次完成判定**：领空后读 DB 终态 → 按 `metric` 取 finished top1 回写 `strategy.best_params`（沿用原 sweep 排序逻辑，数据源从 gather 结果改为 DB 终态）

#### Scenario: 16 组合 sweep 走 worker 队列

- **WHEN** EvTrade 预建 16 行 queued task（batch_no=B），调 `/internal/run-batch`
- **THEN** 立即 202，起 2 个 worker
- **AND** 两 worker FIFO 领取 → 有界并发跑 backtest（一次最多 2 个）
- **AND** 每完成一个 task，`update_task_status('finished')` → WS 逐 task 推前端
- **AND** 16 个全非 queued 后，top1 回写 best_params

## ADDED: worker 队列堵塞自愈 + 代际隔离（run_generation）

回测任务是 `asyncio.to_thread` 跑同步 `run_backtest`——**线程无法强杀**。一个卡死的任务会占住 worker 槽位。解法：

- **`strategy_task.run_generation` 列**（INT NOT NULL DEFAULT 0）：兼作**代际 + 重跑计数器**
  - claim 领取时 `run_generation = run_generation + 1`，worker 记下本次代际
  - `run_backtest` 的 progress 写（`patched_next`）+ 终态写（result/status）都带 `WHERE run_generation = 本次代际`
  - **孤儿线程**（被复位重跑后仍在后台跑的旧线程）晚到的写因代际不匹配 → **自动 no-op**，不覆盖新那次的结果/心跳
- **堵塞检测 = 心跳 stale（非墙钟死等）**：worker 池挂 watchdog 轮询在跑 task 的 `updated_at`（`patched_next` 每 ≥0.5s 写 progress + `updated_at`）。**running 且 `updated_at` 超 `backtest_task_stale_seconds`（默认 120s）没动 = 堵塞** → 区分"慢但活着"（大回测持续推 `updated_at`，不误杀）与"真卡死"
- **重跑**：堵塞时该 task **回 `status='queued'` + `run_generation` 已 +1**，worker 复位（复位状态，非重启进程）去领下一个；该 task 因未完成会被再次领取执行
- **重跑上限**：`run_generation > backtest_max_retries`（默认 3）→ 标 `status='failed'`（`error_msg='blocked, max retries exceeded'`），防无限重跑

#### Scenario: 任务卡死被自愈重跑

- **WHEN** worker 领到 task X（gen=1）跑 backtest，线程卡住不推进 `updated_at`
- **THEN** watchdog 检测到 X `running` 且 `updated_at` stale > 120s
- **AND** X 回 `status='queued'`（gen 仍 1，下次领取 +1=2），worker 复位领下一个
- **AND** X 被再次领取（gen=2）重跑；旧线程（gen=1）晚到的 result/progress 写因 `WHERE run_generation=1` 不匹配 gen=2 行 → no-op
- **AND** 若 X 连续 3 次（gen>3）都卡死 → `status='failed'`

## ADDED: /internal/run-batch 统一队列端点

- `POST /internal/run-batch` body `{strategy_id, batch_no, user_id, script_id, stock_code, backtest_start_date, backtest_end_date, metric, concurrency, period}`（require internal token）
- 语义：批次 N 行 queued task 已由 EvTrade 预建；本端点只**立即 202 + 起 worker 池**（`asyncio.create_task(run_worker_pool(...))`），不阻塞
- `/internal/run-sweep-task`（保留兼容）与 `/internal/run-task`（backtest 单任务）内部转调 `run_worker_pool` → **single + sweep 统一队列**
- **live 路径不变**：`/internal/run-task` mode=live 仍走原 LiveRunner（strategy_orders 母单用），不经 worker 队列
