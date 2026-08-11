# Spec Deltas — strategy

## ADDED Requirements

### REQ-STRAT-020: 策略母单与实盘下单 (v126 change, 2026-08-11)

承接 v125 Part 2（§8 拆出）。策略模块 v125 切纯回测后，本 change 重建**实盘下单**入口：用户为已回测出 `best_params` 的策略创建**母单 `strategy_order`**，母单启动后复用 `strategy_exec` LiveRunner 跑实盘，触发的真实子单归因到母单。

**数据模型**（迁移 `2026-08-11-add-strategy-order.py`）:

- 新表 `strategy_order`（母单）：`id` / `task_id`（UNIQUE, `order_no_seq` 的 `strategy_order` 生成器）/ `user_id` / `strategy_id` / `stock_code`（冗余自 `strategy.stock_code`）/ `status`（`stopped` 默认 / `running` / `closed`）/ `active_task_id`（当前 live `strategy_task.id`）/ `run_count` / `last_started_at` / `last_stopped_at` / `closed_at` / 时间戳。索引 `UNIQUE(task_id)` + `KEY(user_id)` + `KEY(strategy_id)`。
- `orders.strategy_type` 列 COMMENT 更新（0=普通单 / 1=快速做T / **2=策略下单**），列类型 TINYINT 不变。`server/api/orders/schemas.py` 的 `strategy_type: Literal[0, 1]` → `Literal[0, 1, 2]`；`OrderOut.strategy_type` 注释同步。
- `strategy_task` 不改结构（v125 仅删 API 层 `/live`；表字段本就支持 `mode='live'`）。母单**不存 params**：每次启动读当前 `strategy.best_params` 快照到 `strategy_task.params`。

**信号链路（方案 B：payload 携带 `parent_task_id` + `strategy_name`）**:

- `strategy_exec`：`Signal` 加 `parent_task_id: Optional[int]` + `strategy_name: str`（`asdict` 自动序列化）；`_set_task_meta` / `LiveRunner` / `start_live_runner` / `RunTaskRequest` 全部加 2 个带默认值的可选参数，回测路径签名兼容。
- EvTrade `signal_consumer` 改为：
  - `task_id = payload.parent_task_id`（母单 `task_id` → `orders.task_id`）
  - `user_def = payload.strategy_name`（策略名）
  - `strategy_type = 2`
  - 回测信号（`mode == 'backtest'` / `parent_task_id is None`）仍跳过不下单；INFO 仍跳过。

**母单 REST（`/api/script-strategy/strategy-orders`，仅 owner / admin）**:

| 端点 | 行为 |
|---|---|
| `POST /strategy-orders` body `{strategy_id}` | 校验策略存在 + owner（他人私有→`404 STRATEGY_NOT_FOUND`，不泄漏）+ `best_params` 非空（否则 `400 NO_BEST_PARAMS`）→ `next_seq("strategy_order")` 生成 `task_id` → 建母单（`status=stopped`）→ 201 |
| `GET /strategy-orders` | 我的母单列表（admin 全部），JOIN 策略名 + 子单数（`orders.task_id=母单.task_id` COUNT） |
| `GET /strategy-orders/{id}` | 详情（策略名 / 标的 / 状态 / `run_count` / 子单数） |
| `POST /strategy-orders/{id}/start` | 校验非 `closed`（否则 `409 INVALID_STATE`）→ 读 `strategy.best_params`（空→`400 NO_BEST_PARAMS`）→ `create_task(mode='live', ...)` → 转发 `/internal/run-task` 带 `parent_task_id`+`strategy_name` → `status=running`、记 `active_task_id`、`run_count+1`、`last_started_at` |
| `POST /strategy-orders/{id}/stop` | 校验 `running` 且 `active_task_id`（否则 `409 INVALID_STATE`）→ 转发 `/internal/stop-task(active_task_id)` → `status=stopped`、`active_task_id=NULL`、`last_stopped_at` |
| `POST /strategy-orders/{id}/close` | 校验非 `running`（否则 `409`）→ `status=closed`、`closed_at`（**保审计不硬删**） |

错误码：`404 STRATEGY_NOT_FOUND`（含他人私有存在性隐藏）/ `400 NO_BEST_PARAMS` / `409 INVALID_STATE` / `403 FORBIDDEN`。

**权限**：仅 owner（或 admin）可建/启/停/关母单；他**人公开**策略的 `best_params` 不外露（REQ-STRAT-019 精简视图），**不可建母单**（与 v125 R5 一致）。

**前端**：

- 新页 `client/src/views/StrategyOrder.vue`，路由 `/strategy-order`，桌面 NavBar 加「策略下单」入口（BottomNav 不加）。
- 4 面板：**策略下单**（下拉选自己策略，**仅 `best_params` 非空可选中**，空时置灰「需先回测出最佳参数」→ 显示标的 / 「已回测」标记 / 「创建母单」）/ **行情面板**（复用 `QuotePanel.vue`，跟随选中母单/策略的 `stock_code`）/ **策略母单**（`GET /strategy-orders` 列表，含 task_id / 策略名 / 标的 / 状态徽章 / `run_count` / 子单数 / [启动|停止] / 关闭，选中行联动子单面板）/ **委托子单**（`holdings.orders.filter(o => o.strategy_type===2 && Number(o.task_id)===选中母单.task_id)`，T0Trade 同款本地缓存过滤，实时）。
- **T0 视图防御过滤**：`T0Trade.vue` 委托过滤加 `strategy_type !== 2` 条件，与策略单按 `strategy_type` 互斥，防 `task_id` 撞号串视图。
- 状态徽章：`stopped`=默认 / `running`=进行中 / `closed`=已关闭；`running` 禁用「关闭」，`closed` 禁用「启动」。

#### Scenario: 母单可重复启停 + 子单累积归因

- **GIVEN** 用户 A 的策略 `s1`（`best_params` 非空，标的 600519.SH）
- **WHEN** A 调 `POST /strategy-orders {strategy_id: s1}` → 启动 → 停止 → 启动（第二次）
- **THEN** 母单 `status` 走 `stopped → running → stopped → running`；`run_count=2`；`active_task_id` 在两次启动间变化（指向各自的 `strategy_task.id`）；两次运行的子单全部 `orders.task_id = 母单.task_id` + `strategy_type=2` + `user_def=策略名`，可按母单统一过滤

#### Scenario: 无 best_params 拒绝建母单

- **GIVEN** 用户 A 的策略 `s2`（`best_params` 为 NULL）
- **WHEN** A 调 `POST /strategy-orders {strategy_id: s2}`
- **THEN** 返回 `400 {"code": "NO_BEST_PARAMS"}`，未建母单、未占 `task_id`

#### Scenario: 他人公开策略不可建母单

- **GIVEN** 用户 A 的策略 `s3`（`is_public=true`），用户 B 看到精简视图
- **WHEN** B 调 `POST /strategy-orders {strategy_id: s3}`
- **THEN** 返回 `403 {"code": "FORBIDDEN"}`（B 已在列表看到 `s3`，存在性无需隐藏；best_params 仍不外露）

#### Scenario: 非法状态转移

- **GIVEN** 母单 `o1` 处于 `running`
- **WHEN** A 调 `POST /strategy-orders/o1/start`（再启）
- **THEN** 返回 `409 {"code": "INVALID_STATE"}`
- **AND** A 调 `POST /strategy-orders/o1/close` → 同 `409`
- **AND** `o1` 处于 `closed` 时调 `start` → `409`

#### Scenario: T0 视图与策略单互斥

- **GIVEN** T0 委托 `o_t0`（`strategy_type=1`）+ 策略子单 `o_strat`（`strategy_type=2`），`task_id` 同值
- **WHEN** T0Trade.vue 渲染委托列表
- **THEN** `o_t0` 出现，`o_strat` 被 `strategy_type !== 2` 过滤排除
- **AND** StrategyOrder.vue 渲染子单面板：仅 `o_strat` 出现，`o_t0` 被 `strategy_type===2` 过滤排除

## Cross References (modified)

- 委托下发：`trading/spec.md` REQ-TRADE-002（place 流程 + user_def 关联） + `data-model/spec.md` §14 `orders.strategy_type` 列（0/1/**2** 扩展）
- 策略数据：`data-model/spec.md` `strategy` 表 + `REQ-STRAT-019` `is_public` / `stock_code` / `best_params` 门禁
- 引擎：`strategy-exec/spec.md` REQ-SE-003~005（Backtrader 引擎 / RabbitMQ 信号 / 用户脚本接口） + REQ-SE-008~009（LiveRunner / Signal payload）
- 前端：`frontend/spec.md`（ScriptDev.vue / ScriptTask.vue / StrategyOrder.vue / T0Trade.vue 防御过滤）
