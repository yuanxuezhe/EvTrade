# tasks.md — 实施 checklist

> 配套 [proposal.md](./proposal.md)。
> 每个 Phase 独立可 review / merge。

## Phase 1 — 知识库 (knowledge first)

- [ ] 写 `proposal.md` (本 change 顶层)
- [ ] 写 `design.md` (注入机制 / sweep 引擎 / 数据流图)
- [ ] 写 `tasks.md` (本文件)
- [ ] `spec-deltas/strategy-exec.md` (新增 REQ-SE-008 sweep + REQ-SE-009 live 接 best)
- [ ] `spec-deltas/data-model.md` (strategy_task 加 3 列)
- [ ] `spec-deltas/strategy.md` (REQ-STRAT-016 端点签名扩展)

## Phase 2 — Schema 注入 (核心,无 sweep 也能 ship)

- [ ] `strategy_exec/strategy_exec/sandbox/loader.py`:
  - [ ] 加 `_inject_params_from_schema(cls, params_schema: list) -> Type`
  - [ ] `_extract_params_keys(cls)` AST 扫 `cls.params` 取 key 集合
  - [ ] strict 模式:declared ≠ schema → raise ValueError,提示 code 多/少的 keys
  - [ ] `load_strategy_class(code, project_strategy_cls, params_schema=None)` 签名扩 1 参
  - [ ] backward compat:`params_schema=None` → 走老逻辑 (不 inject)
- [ ] `strategy_exec/strategy_exec/engines/backtrader/backtest.py:104-112`:
  - [ ] `script_row = get_script(user_id, script_id)` 后多读 `script_row["params_schema"]`
  - [ ] `load_strategy_class(code, ProjectStrategy, params_schema=params_schema)`
- [ ] `strategy_exec/strategy_exec/engines/backtrader/live.py:start_live_runner`:
  - [ ] 同 backtest.py 改造 (live 路径)
- [ ] 写 `tests/server/strategy/test_loader_inject.py`:
  - [ ] `test_schema_injects_params_to_class`
  - [ ] `test_code_params_mismatch_schema_raises_strict`
  - [ ] `test_code_no_params_schema_injects_from_defaults`
  - [ ] `test_backward_compat_no_schema_keeps_old_behavior`
- [ ] 跑回归:`uv run python -m pytest tests/server/api/test_ws_endpoint.py tests/server/strategy/ -v`

## Phase 3 — DB 迁移 (3 列 nullable)

- [ ] `server/migrations/2026-08-11-add-strategy-sweep-fields.py` (新建):
  - [ ] `ALTER TABLE strategy_task ADD COLUMN sweep_id VARCHAR(32) NULL` (有幂等检查)
  - [ ] `ALTER TABLE strategy_task ADD COLUMN sweep_metric VARCHAR(32) NULL`
  - [ ] `ALTER TABLE strategy_task ADD COLUMN sweep_total INT NULL`
  - [ ] `server/migrations/__init__.py` 注册 + 顺序号确认
- [ ] `server/tables/strategy_task.py` 类定义补 3 个字段 (跟 DB 同步)
- [ ] `tests/server/strategy/test_migration.py`:
  - [ ] `test_sweep_columns_exist_and_nullable`

## Phase 4 — Sweep 引擎 (新文件)

- [ ] `strategy_exec/strategy_exec/engines/backtrader/sweep.py` (新建,目标 ≤250 行):
  - [ ] `iter_param_grid(param_grid: dict) -> Iterator[dict]` 笛卡尔积
  - [ ] `validate_grid_size(grid_size: int) -> None` 软 64 / 硬 512
  - [ ] `run_sweep(user_id, script_id, stock_code, param_grid, metric, sweep_id, ...) -> dict`:
    - [ ] 并发用 `asyncio.Semaphore(N)` (N=2 默认)
    - [ ] 每个组合 = 1 个 strategy_task row (status='pending' → 'running' → 'finished'/'failed')
    - [ ] 共享 sweep_id 标识
    - [ ] 全部完成后写 `summary_task`:best_params + sweep_results (JSON) + sweep_total
- [ ] `strategy_exec/strategy_exec/data_access/strategy_task.py`:
  - [ ] 加 `create_sweep_task(user_id, script_id, params, sweep_id, sweep_metric)` 辅助函数
  - [ ] 加 `update_sweep_summary(task_id, sweep_results, best_params)` 写扫结果
- [ ] `strategy_exec/strategy_exec/api/internal.py`:
  - [ ] 新增 `RunSweepTaskRequest` Pydantic schema
  - [ ] `POST /internal/run-sweep-task` endpoint
- [ ] `tests/server/strategy/test_sweep.py`:
  - [ ] `test_cartesian_product_iter`
  - [ ] `test_soft_limit_64_warns`
  - [ ] `test_hard_limit_512_raises`
  - [ ] `test_sweep_id_shared_across_tasks`
  - [ ] `test_best_params_picked_by_metric`

## Phase 5 — EvTrade 转发端点

- [ ] `server/api/script_strategy/endpoints.py`:
  - [ ] `POST /api/strategy/tasks/{id}/run-sweep` 转发到 strategy_exec
  - [ ] `GET /api/strategy/tasks?script_id=&status=finished&has_best_params=1` 查询
  - [ ] `TaskRun` 加 `mode='sweep'` 分支
- [ ] `client/src/api/script_strategy.js`:
  - [ ] 加 `runSweepTask(taskId, params, paramGrid)` API wrapper
  - [ ] 加 `listFinishedBacktests(scriptId)` API wrapper
- [ ] `tests/server/api/test_strategy_endpoints.py` (或加到现有):
  - [ ] `test_run_sweep_forwards_to_strategy_exec`
  - [ ] `test_list_finished_backtests_filters_correctly`

## Phase 6 — 前端 UI

- [ ] `client/src/components/SweepForm.vue` (新建子组件):
  - [ ] 表单:选脚本 → 拉 schema → 每字段显示 [ ] lock / [slider/select] 范围
  - [ ] 默认范围从 schema 取 (min..max step)
  - [ ] 显示预计组合数 + 警告 (>64 黄 / >512 红)
  - [ ] 选 metric 下拉 (sharpe / total_return / calmar)
  - [ ] 提交: 调 `runSweepTask` API
- [ ] `client/src/views/ScriptTask.vue`:
  - [ ] 启动任务表单加 tab: [单次回测] [参数扫描]
  - [ ] 选扫描 → 嵌入 `<SweepForm>` 子组件
  - [ ] 启实盘表单加 "参数来源" radio: 默认值 / 从历史回测选 / 手动
  - [ ] "从历史回测选" 拉 `<BacktestPicker>` 弹窗:列某脚本历史 backtest,点选自动填 params
  - [ ] 跑完 sweep 后任务详情页:列 sweep_results 表格 (按 metric 降序)
- [ ] `client/src/components/BacktestPicker.vue` (新建):
  - [ ] 列表 + sharpe/pnl/badge
  - [ ] 点选 → 返 best_params dict
- [ ] 手工 e2e 验证:UI 跑一遍 4 组合 sweep,看后端日志确认 4 个 task + 1 个 summary

## Phase 7 — 存量 demo 脚本迁移

- [ ] `server/migrations/2026-08-11-drop-mas-v1-params-from-code.py` (新建):
  - [ ] 读 `strategy_script.code` WHERE id='mas_v1'
  - [ ] 用正则删 `    params = \(\n        \("fast", 5\),\n.*?"rsi_period", 14\),\n    \)\n\n` 块
  - [ ] UPDATE strategy_script SET code=?, updated_at=NOW() WHERE id='mas_v1'
  - [ ] 幂等:删前先 grep 确认 `params = (` 块还在
- [ ] `tests/server/strategy/test_mas_v1_migration.py`:
  - [ ] `test_mas_v1_code_no_longer_has_params_tuple`

## Phase 8 — Spec sync + 归档

- [ ] `openspec/specs/strategy-exec/spec.md`:新增 REQ-SE-008 / REQ-SE-009 (sweep 内容)
- [ ] `openspec/specs/data-model/spec.md`:strategy_task 表描述加 3 列
- [ ] `openspec/specs/strategy/spec.md`:REQ-STRAT-016 端点签名扩展
- [ ] 跑全量回归 pytest (含新加的 test_loader_inject / test_sweep / test_migration)
- [ ] commit & push (按 CLAUDE.md 多 commit 粒度:每 phase 一 commit)
- [ ] 归档: `openspec/changes/2026-08-10-strategy-params-sweep-best-live/` → `archive/` (opsx:archive)

## 不做 (out of scope, 留 follow-up)

- ❌ 在线实盘参数热更新 (单独 change)
- ❌ 多 metric 并行排序 (单独 change)
- ❌ Sweep 结果可视化对比图 (单独 change)
- ❌ 跨脚本 best_params 复用 (schema 重设计)