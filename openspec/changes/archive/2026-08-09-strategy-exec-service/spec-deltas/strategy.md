# spec-delta: strategy（现有 spec 增量）

## REMOVED Requirements

### REQ-STRAT-014 ~ REQ-STRAT-017（脚本策略模块，v90）— 已迁移到独立服务

> **变更说明（2026-08-09）**：脚本策略模块（ScriptDev / ScriptTask / 回测 / 实盘 / 14 个 REST 端点 / Backtrader 引擎 / RabbitMQ 推送）已迁移到独立服务 `EvTrade/strategy_exec/`。
>
> **BREAKING**：现有用户脚本（`on_bar` / `on_tick` / `ctx.lib.doorder`）需重写为 Backtrader `bt.Strategy` + `self.buy_signal()` 接口。详见 `strategy_exec/README.md` + `docs/strategy-migration-v90-to-bt.md`。

以下 4 个 Requirement **从本 spec 删除**（已迁出）：

- ~~REQ-STRAT-014: 脚本策略数据模型（2 张表 + strategy_task 扩展）~~ → 迁到 `strategy-exec/spec.md` §"数据模型"
- ~~REQ-STRAT-015: script-strategy REST API（14 端点）~~ → 迁到 `strategy-exec/spec.md` REQ-SE-002 + 仍由 EvTrade `/api/script-strategy/*` 转发
- ~~REQ-STRAT-016: 回测 / 实盘引擎运行时~~ → 迁到 `strategy-exec/spec.md` REQ-SE-003
- ~~REQ-STRAT-017: 前端 2 个 view + 14 端点客户端~~ → 仍属 `frontend/spec.md`（前端 0 改动）

## MODIFIED Requirements

### REQ-STRAT-009: REST API（调整：script-strategy 端点改为转发）

`server/api/script_strategy/endpoints.py` 的 script CRUD endpoint **保持不变**（POST/PUT/DELETE/GET scripts）：

- 这些端点直接写 DB（`StrategyScript` 表），不依赖 strategy_exec

但 task 端点 `POST /tasks/{id}/run` 和 `POST /tasks/{id}/stop` **改为转发**：

- 原行为：直接调 `service.run_task()`（同进程启动 Backtrader）
- 新行为：HTTP POST `strategy_exec:8001/internal/run-task`，strategy_exec 异步执行
- EvTrade 端返 202 + task 详情
- 状态字段 `strategy_task.execution_service='strategy_exec'`

#### Scenario: run_task 转发

- **WHEN** 客户端 POST `/api/script-strategy/tasks/123/run` {mode:'backtest', ...}
- **THEN** EvTrade 转发 HTTP POST `strategy_exec:8001/internal/run-task`
- **AND** EvTrade 立即返 202 + task 详情（status='queued'）
- **AND** strategy_exec 异步启动 Backtrader，写 `strategy_task.status='running'`, `execution_service='strategy_exec'`

### REQ-STRAT-011: WS payload `strategy_update` 频道（不变）

- 仍由 `server/services/strategy/engine.py`（网格策略引擎）推送
- 与脚本策略运行独立 —— 网格策略不发 script 事件，script 也不发网格事件

### REQ-STRAT-012: Order.user_def 关联（不变）

### REQ-STRAT-013: T0 端点 JOIN 迁移（不变）

## ADDED Requirements

### REQ-STRAT-018: 脚本策略运行指向 strategy_exec

> **新需求（2026-08-09）**：明确脚本策略运行的服务归属。

`strategy_task.execution_service` 字段标识策略运行的服务：

- `'evtrade'` = 老服务（v120 之前，本 change 完成后已无此值）
- `'strategy_exec'` = 新独立服务（v120+ 所有脚本任务）

#### Scenario: 查询 task 显示执行服务

- **WHEN** admin 查 `strategy_task` 表
- **THEN** 所有 v120+ 创建的 task 的 `execution_service='strategy_exec'`
- **AND** 老 v90~v118 期间的 task 默认 `'evtrade'`（migration 时回填默认值）

### REQ-STRAT-019: 网格策略保持独立

> **澄清（2026-08-09）**：本 change **不影响**网格策略引擎。

- `server/services/strategy/quote_consumer.py`（WS 行情消费 + 网格 strategy 引擎）
- `server/services/strategy/engine.py`（网格 evaluate_tick + WS strategy_update 推送）

仍由 EvTrade 主进程执行，与 script-strategy **并行存在**，互不影响。

#### Scenario: 网格策略 + 脚本策略同时跑

- **WHEN** admin 配置 3 个网格 strategy + 启 1 个 script live task
- **THEN** 网格 strategy 由 `quote_consumer.py` 后台跑（EvTrade 进程）
- **AND** script task 由 strategy_exec 进程跑
- **AND** 两者通过不同的 ws channel 推前端（`strategy_update` from 网格, `task_progress_update` from script）
- **AND** 互不干扰

## Cross References

- 脚本策略完整需求：`strategy-exec/spec.md` REQ-SE-001 ~ REQ-SE-007
- 数据模型：`data-model/spec.md` §8 strategy_task（3 新字段说明）
- 前端：`frontend/spec.md` REQ-FE-310（/script-task 路由不变）
- 部署：`dev-process-control/spec.md` §"进程管控"（多进程管理）