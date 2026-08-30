# Tasks: sweep-worker-queue (2026-08-30)

> 每个 task = 1 个 commit（v6 单 commit 单目的）。两阶段一起做（Phase 1 提交性能 + Phase 2 worker 队列）。
>
> **✅ 2026-08-30 全部完成并归档。** commit `ee2c7bb`(骨架) + `b2c2b91`(批量INSERT) + `e00709d`(to_thread) + `dc6410e`(migration run_generation) + `f16c4dc`(worker 数据层) + `9c5d9d1`(worker.py) + `2208b59`(API run-batch) + `83599eb`(server 转发) + `bbede24`(KB+spec)。
> 验收：pytest 全过（server 98 / strategy_exec 129）/ run_generation 列已 apply / /internal/run-batch 已注册 / 服务重启健康。
> 已知限制：worker 池每次触发临时起（内存态），进程崩溃不自动续跑历史批次 queued 任务（需重测/重新提交）——与"每次触发拉起 worker"拍板一致。

## P0 — change 骨架 + step-0 KB

- [x] **commit 0 (骨架 + step-0 KB)**
  - 新建 change `{proposal.md, tasks.md, spec-deltas/{strategy-exec.md, data-model.md}}`
  - step-0 KB 缺口：`openspec/specs/data-model/spec.md` + `知识库/数据库/Schema说明.md` 登记 strategy_task 加 `run_generation` 列
  - 验收：proposal/tasks/spec-delta 三件齐全

## P1 — Phase 1: 提交性能（修"设置时超时"主因）

- [x] **commit 1 — batches 批量 INSERT**
  - `create_backtest_batch`：Strategy 查一次（循环外）；N 行 task 改 executemany 批量 INSERT
  - 验收：512 组合只 1 次批量 INSERT；单测（批量插入条数 / id 回收）

- [x] **commit 2 — 端点 to_thread 包装**
  - `strategies.backtest_endpoint` + `retest_batch_endpoint`：DB 写 `create_backtest_batch` 用 `await asyncio.to_thread(...)` 包装
  - 验收：event loop 不阻塞（async 路由不再同步调 DB）

## P2 — migration + schema + ORM

- [x] **commit 3 — migration run_generation 列**
  - `server/migrations/2026-08-30-add-strategy-task-run-generation.py`：`ADD COLUMN run_generation INT NOT NULL DEFAULT 0`（幂等 INFORMATION_SCHEMA）
  - `server/schema.yml` + `server/tables/strategy_task.py` 加列
  - 跑 `sync_schema.py diff` 确认只 ADD 1 列 → apply
  - 验收：`SELECT run_generation FROM strategy_task LIMIT 1` 可查（默认 0）

## P3 — Phase 2: worker 队列核心（strategy_exec）

- [x] **commit 4 — data_access: claim + 代际守卫**
  - `claim_next_queued(strategy_id, batch_no, execution_pid, gen_cap)`：SKIP LOCKED 选 + 乐观 UPDATE 领取（rowcount>0 成功）
  - `update_task_status` / `update_task_progress` / result 写：加 `run_generation` 守卫参数（None=不过滤，向后兼容）
  - 单测：claim 互斥（两 worker 抢同一 id 只一个成）/ 代际 no-op（旧代际写被拒）/ 重跑上限
  - 验收：pytest 新测全过

- [x] **commit 5 — worker.py worker 池 + 堵塞自愈**
  - `_worker()`: 循环 claim → to_thread run_backtest(带 run_generation) → 领下一个
  - `run_worker_pool(...)`: gather N worker + 拉 1 次 K 线共享 + watchdog（stale 检测 → 回 queued + 代际+1，超限 failed）
  - 批次完成判定：领空后读 DB 终态 → top1 回写 best_params（沿用 sweep 逻辑）
  - config：`backtest_task_stale_seconds`(120) / `backtest_max_retries`(3)
  - 单测：worker 池 FIFO / 堵塞复位 / 孤儿线程代际守卫 / 重跑上限
  - 验收：pytest 全过

- [x] **commit 6 — API /internal/run-batch + 转调**
  - 新增 `POST /internal/run-batch`（202 + create_task 起 worker 池）
  - `/internal/run-sweep-task` / `/internal/run-task`(backtest) 转调 run-batch（统一队列）
  - `backtest.py run_backtest` 加 `run_generation` 参数 + progress/result 写带代际
  - 验收：import OK；单任务/sweep 都走 worker 池

## P4 — server 转发统一 run-batch

- [x] **commit 7 — forward + 端点改调 run-batch**
  - `forward.py`：加 `_forward_run_batch`；backtest/retest 端点 single+sweep 都转 run-batch
  - 验收：`npm run build` 不受影响；单测（转发 payload）

## P5 — 知识库 + spec 同步

- [x] **commit 8 — docs(knowledge+spec)**
  - `strategy-exec/spec.md`：REQ-SE-008 改 worker 队列执行模型 + 新增 worker 队列/堵塞自愈段
  - `data-model/spec.md` + `Schema说明.md`：strategy_task run_generation 列
  - `Backtrader引擎.md`：worker 池 + 代际 + 堵塞自愈段
  - `脚本策略模块.md`：提交批量 INSERT + to_thread + 转发 run-batch
  - `策略开发与运行.md`：提交立即返回、逐任务状态更新
  - 验收：grep run_generation / worker 在知识库命中

## P6 — 归档

- [x] **commit 9 — docs(openspec) 归档**
  - spec 合并 + mv 到 archive + AGENTS 行
  - 验收：changes/ 只剩 archive

## 验证 (v6 完成自查)

- [x] `pytest tests/strategy_exec/ server/tests/ -q` 全过（新增 claim/worker/generation 单测全过）
- [x] 512 组合提交 < 2s 返回，event loop 不阻塞
- [x] 端到端：sweep 提交 → 202 → worker 池 FIFO 逐个跑 → 前端逐行状态更新 → 点任务看详情
- [x] 堵塞自愈：模拟卡死 → stale → 回 queued 重跑 → 超限 failed
- [x] 孤儿线程写 no-op（代际守卫）
- [x] single 走统一队列行为不变；live 母单不受影响
- [x] `sync_schema.py diff` 只 ADD run_generation
- [x] 知识库 + spec 同步；每 commit 单目的；不自动 push
