# Sweep Worker Queue — 回测任务队列化 + 堵塞自愈 (2026-08-30)

> 用户拍板 2026-08-30：参数扫描回测会**超时**。优化方案 = **统一回测任务队列**：
> 每次触发回测（single + sweep）时，为批次产生的批量任务**每个建一条 queued 行**入库排队，**立即返回前端**（不等执行）；
> 然后**每次触发拉起 N 个 worker**（N=concurrency），**FIFO 有界并发**按顺序从队列领任务跑回测、逐个记结果、**逐任务通知前端**（现有 WS/轮询已具备）；
> **worker 执行单个任务若堵塞超过阈值（心跳 stale），worker 复位该任务（回 queued + 代际+1）并去领下一个，堵塞任务因未完成会被重跑**。
>
> 两阶段一起做（用户选 "2"）：Phase 1 修提交性能（很可能就是"设置时超时"主因）+ Phase 2 worker 队列 + 堵塞自愈。

## Why

**两个独立成因，都要治：**

### 成因①：提交阶段同步 IO 阻塞（"设置扫描时超时"主因）
`strategies.backtest_endpoint`（async 路由）里**同步**调 `create_backtest_batch`：
- sweep 模式对 N 个组合 `for c in combos: create_task(...)`（`batches.py:100-111`），每个 `create_task` = 1× `Strategy.query_one`(SELECT) + 1× INSERT，**~1000+ 次串行 DB 往返**
- 无 `asyncio.to_thread` 包装 → **阻塞单进程 uvicorn event loop**（CLAUDE.md §七 明令禁止的 async 路由调同步 IO）
- 大扫描轻松吃满前端 axios `timeout: 15000`（`http.js:25`），还会卡住整个后端其他请求

### 成因②：执行是一把梭内存态，非真队列（执行脆弱）
`sweep.run_sweep_batch` `asyncio.gather(*(_run_one(t) for t in tasks))`：
- 整个批次是 strategy_exec 里**一个 `asyncio.create_task` 内存对象**，无持久队列
- 进程崩/重启 → 整批丢失；单任务卡死 → 永久 `running`（`list_stale_queued_tasks` 只监控不处理）
- best_params 只在最末写一次，无增量可见性

**前端逐任务可见性基本已存在**（批次行=队列项，建出来即 `queued`；`BatchTasksTable` 显示 status+进度环；`run_backtest` 每完成一个 task `update_task_status("finished")` → 现有 `task_progress_update` WS 逐 task 推；已有 3s 轮询兜底 `_hasActiveTask`）。**改动重心在后端（提交性能 + 执行模型），前端几乎不动。**

## What

### Phase 1 — 提交性能（低风险，先做）

- `batches.create_backtest_batch`：N 行 task 改**批量 INSERT（executemany）**，`Strategy` 只查一次（循环外），去掉 per-row SELECT。
- `strategies.backtest_endpoint` + `retest_batch_endpoint`：DB 写用 `await asyncio.to_thread(...)` 包装，不阻塞 event loop。
- 验收：512 组合提交从"卡 1000+ 次往返"降到"1 次批量 INSERT"，event loop 不阻塞，前端不再 15s 超时。

### Phase 2 — worker 队列 + 堵塞自愈

**新执行模型**（`strategy_exec/engines/backtrader/worker.py`，职责单一）：
- **每次触发拉 N 个 worker**：`asyncio.gather(*[_worker() for _ in range(N)])`，N = `concurrency`（默认 2）。
- **worker 循环**（FIFO 有界并发）：
  1. **原子领取**：`claim_next_queued(strategy_id, batch_no, execution_pid, gen_cap)` — `SELECT id … WHERE status='queued' AND run_generation < :cap ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED`（MySQL 8）→ 拿到 id 后 `UPDATE … SET status='running', execution_pid, run_generation+1 WHERE id=? AND status='queued' AND execution_pid IS NULL`（`rowcount>0` 才算领到，防 N worker / 多实例抢同一 task）。
  2. 跑 `run_backtest`（`asyncio.to_thread`），带本次 `run_generation`。
  3. 领下一个，直到批次队列空。
- **堵塞检测（心跳 stale，非墙钟死等）**：watchdog 轮询在跑 task 的 `updated_at`（`run_backtest` 的 `patched_next` 每 ≥0.5s 写 progress+`updated_at`）。**running 且 `updated_at` 超 `backtest_task_stale_seconds`（默认 120s）没动 = 堵塞** → 区分"慢但活着"（大回测照常推进不误杀）与"真卡死"。
- **重跑 + 代际隔离**（关键，`to_thread` 线程杀不掉）：
  - 堵塞时：该 task **回 `queued` + `run_generation+1`**，worker 复位去领下一个（"worker 自己重启"= worker 复位，**非进程重启**）。
  - `run_generation` 列（migration，默认 0）当**代际 + 重跑计数器**：claim 时 +1；所有写（progress/result/终态）带 `WHERE run_generation=我的代际` → **孤儿线程晚到的写自动 no-op**，不覆盖新那次的结果/心跳。
  - `run_generation > 重跑上限（默认 3）` → 标 `failed`（`error_msg="blocked, max retries"`），防无限重跑。
- **K 线共享**：每 worker 池启动时拉 1 次 `fetch_his_bars`（批次共享），传进各 `run_backtest`。
- **single/sweep 统一**：single（1 行）+ sweep（N 行）都建 queued 行 → 走同一 worker 池端点。`run-task` 的 **live 路径不动**（`strategy_orders.py` 母单用，非 backtest）。
- **批次完成判定**：worker 池领空后（无 queued），批次所有 task 非 queued → 按 metric 取 finished top1 回写 `best_params`（沿用 `sweep.py` 现有逻辑，从 gather 结果改为读 DB 终态）。

**API 变更**（strategy_exec `/internal`）：
- 新增/改造 `POST /internal/run-batch`：入参 `{strategy_id, batch_no, user_id, script_id, stock_code, dates, metric, concurrency, period}` → 立即 202 + 起 worker 池（`asyncio.create_task`）。
- `/internal/run-sweep-task` 保留兼容（内部转调 run-batch）；`/internal/run-task` backtest 单任务也转调 run-batch（统一队列）。

**不做什么**：
- 不重启进程（worker 复位即可）。
- 不引入 Redis/Celery（DB 表 = 队列，乐观锁领取，无新依赖）。
- 不动 iquant/broker。
- 不动 live 母单执行路径。
- 前端不改（逐任务可见性现成）。
- 不做 WS 批次级"全部完成"广播（best_params 回写 + 各行 status 变化已够前端收敛）。

## 影响面

| 模块 | 影响 |
|---|---|
| `server/migrations/2026-08-30-add-strategy-task-run-generation.py` | **新增** migration：`strategy_task` 加 `run_generation INT NOT NULL DEFAULT 0`（幂等） |
| `server/schema.yml` + `server/tables/strategy_task.py` | strategy_task 加 `run_generation` 列 |
| `server/services/script_strategy/batches.py` | create_backtest_batch 批量 INSERT + Strategy 查一次 |
| `server/api/script_strategy/strategies.py` + `forward.py` | backtest/retest 端点 `to_thread` 包装 DB 写 + 转发统一 run-batch |
| `strategy_exec/engines/backtrader/worker.py` | **新增**：worker 池 + 原子领取 + 堵塞 watchdog + 代际重跑 |
| `strategy_exec/engines/backtrader/sweep.py` | 瘦身：保留组合展开纯函数 + 批次完成判定；gather 逻辑迁 worker |
| `strategy_exec/data_access/strategy_task.py` | 加 `claim_next_queued` / `update_task_status`/`update_task_progress`/result 写带 `run_generation` 守卫 |
| `strategy_exec/engines/backtrader/backtest.py` | `run_backtest` 加 `run_generation` 参数（写 result 时守卫）；`patched_next` progress 写带代际 |
| `strategy_exec/api/internal.py` | 新增 `/internal/run-batch`；run-sweep-task / run-task 转调 |
| `strategy_exec/config.py` | `backtest_task_stale_seconds`(120) / `backtest_max_retries`(3) / worker 领取参数 |
| 知识库 | data-model strategy_task 加列 + 策略服务/Backtrader引擎 worker 段 + 后端服务/策略引擎 + 前端说明"提交立即返回" |

## 数据安全 checklist

- [ ] migration 只 ADD `run_generation`（DEFAULT 0），不动现有列/数据；幂等（INFORMATION_SCHEMA 检测）
- [ ] claim 领取用 `SKIP LOCKED`/乐观 UPDATE，不锁全表，无死锁
- [ ] 代际守卫只 no-op 孤儿线程写，不误改正确任务
- [ ] 重跑上限兜底，防无限重跑
- [ ] 测试不碰生产 task 行（纯函数 + mock session）

## 验收 checklist

- [ ] `pytest tests/strategy_exec/ server/tests/` 全过（新增 worker/claim/generation 单测全过）
- [ ] 512 组合提交：< 2s 返回（批量 INSERT + to_thread），event loop 不阻塞
- [ ] 端到端：提交 sweep → 立即 202 → worker 池 FIFO 逐个跑 → 前端逐行 status 更新（queued→running→finished）→ 点任务看 TaskDetail
- [ ] 堵塞自愈：模拟某 task 卡死（心跳停）→ watchdog stale → 回 queued + 代际+1 → 被重跑；超 3 次 → failed
- [ ] 孤儿线程写 no-op（代际守卫单测）
- [ ] single 单次回测也走统一队列，行为不变
- [ ] live 母单路径不受影响
- [ ] 知识库 + spec 同步；每 commit 单目的；不自动 push
