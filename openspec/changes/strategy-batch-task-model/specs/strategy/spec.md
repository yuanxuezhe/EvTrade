# spec-delta: strategy — 策略/批次/任务 三层模型（v123）

> 配套 [proposal.md](../../proposal.md) / [design.md](../../design.md)。脚本库 `strategy_script` 不动；新增 `strategy` 层；任务挂 `strategy_id`；batch 统一回测/扫描/实盘。

## MODIFIED Requirements

### REQ-STRAT-014: 脚本策略数据模型（2 张表 + strategy_task 扩展）

- **`strategy_script`**（脚本库，v90 起复合 PK `(user_id, id)`，**v123 不变**）
  - `id: varchar(64)`（用户自命名）/ `user_id: int` / `name` / `code: longtext` / `params_schema: json`（参数契约 key/type/default/min/max/step/values）/ `description` / `status` / `is_public` / `created_at` / `updated_at`
- **`strategy`**（策略，**v123 新增**，自增 PK `strategy_id`）
  - `strategy_id: int`（自增）/ `user_id: int` / `script_id: varchar(64)` → strategy_script.id / `name: varchar(64)` / `status`(draft/active/archived) / `best_params: json`(NULL=未回测) / `created_at` / `updated_at`
  - 一个脚本可建多个策略；建策略不填参数、不定模式（回测/实盘由运行决定）
- **`strategy_task`**（任务，**v123 重构**）
  - `task_id`（自增 PK）/ `user_id` / `strategy_id` → strategy.id（**删除原 `script_id` 关联**）/ `batch_no`（序号表 `task_batch` 生成）/ `params: json` / `mode`(backtest/live) / `stock_code` / `backtest_start_date` / `backtest_end_date` / `period` / `fields`
  - 结果：`backtest_result` / `pnl` / `trades_count` / `positions` / `started_at` / `finished_at` / `error_msg`
  - 运行态：`status` / `progress` / `version`(乐观锁) / `execution_service` / `execution_pid` / `live_signals`
  - **删除**（v123）：`script_id`、`best_params`、`sweep_id`、`sweep_total`、`sweep_metric`
- **`strategy_script_audit`**（v90，**不动**）：`task_id` 关联任务（间接定位策略→脚本）

#### Scenario: 一个脚本建多个策略

- **WHEN** 用户用脚本 `mas_v1` 分别建策略 A、B
- **THEN** `strategy` 表 2 行 `script_id` 均=mas_v1，`strategy_id` 各自唯一

#### Scenario: task 挂策略不挂脚本

- **WHEN** 为策略 A 发起回测生成 task
- **THEN** task 行 `strategy_id`=A.id，无 `script_id` 字段

#### Scenario: 回测后 best_params 覆盖回写

- **WHEN** 策略 A 某批次回测完成，按 metric 排序取 top1
- **THEN** `strategy.best_params` 覆盖为该 top1 的 params

#### Scenario: 未回测策略 best_params 为空

- **WHEN** 新建策略且未跑任何回测
- **THEN** `strategy.best_params = NULL`

### REQ-STRAT-015: script-strategy REST API（14 端点）

所有端点前缀 `/api/script-strategy`，依赖 `get_current_user`。

**scripts 子资源（脚本库，v123 不变）**：
- `GET /scripts` / `GET /scripts/by-name/{name}` / `GET /scripts/{script_id}` / `POST /scripts` / `PUT /scripts/{script_id}` / `DELETE /scripts/{script_id}`
- `GET /templates/default`

**strategies 子资源（v123 新增）**：
- `GET /strategies` — 列表（user_id=me OR 脚本 is_public=1 的派生策略）
- `GET /strategies/{strategy_id}` — 详情（含 script / best_params / 最近批次）
- `POST /strategies` — 创建 `{name, script_id}`（不填参数、不定模式）
- `PUT /strategies/{strategy_id}` — 更新（仅 user_id=me）
- `DELETE /strategies/{strategy_id}` — 删除

**回测/批次（v123）**：
- `POST /strategies/{strategy_id}/backtest` — body: `{mode: single|sweep, params | param_ranges, stock_code, backtest_start_date, backtest_end_date, period, metric, concurrency}`；生成 1 个 batch + N 行 task，异步返回 `{batch_no, total_runs}`
- `GET /strategies/{strategy_id}/batches` — 批次列表（GROUP BY batch_no：batch_no/created_at/mode/task_count/best）
- `GET /strategies/{strategy_id}/batches/{batch_no}/tasks` — 该批次任务表格数据（参数列 + 结果列）
- `GET /tasks/{task_id}` — 任务详情（params/结果/backtest_result/signals/audit）
- `POST /tasks/{task_id}/stop` — 停止（live 生效）
- `DELETE /tasks/{task_id}` — 删除

**实盘（v123 门禁）**：
- `POST /strategies/{strategy_id}/live` — 校验 `best_params` 非空，否则 400 `NO_BEST_PARAMS`；用 best_params 建 1 个 live batch（1 行 task，mode=live）

#### Scenario: 创建策略不填参数

- **WHEN** `POST /strategies {name, script_id}`
- **THEN** 生成 strategy 行，`best_params=NULL`，无 mode

#### Scenario: 扫描生成批次

- **WHEN** `POST /strategies/{id}/backtest` mode=sweep，param_ranges 展开 16 组合
- **THEN** 生成 1 个 batch（task_batch 序号）+ 16 行 task，每行一组 params

#### Scenario: 未回测禁止实盘

- **WHEN** `POST /strategies/{id}/live` 且 `best_params=NULL`
- **THEN** 返 400 `{"code":"NO_BEST_PARAMS","msg":"请先回测生成最优参数"}`，不建任何 task

#### Scenario: 实盘用 best_params 建批次

- **WHEN** `best_params={fast:7,slow:30}`，`POST live {stock_code, fields}`
- **THEN** 建 1 行 task：`mode=live`、`params=best_params`、新 `batch_no`

### REQ-STRAT-016: 回测 / 实盘引擎运行时（v120 已迁移 strategy_exec, v122 扩 sweep + best）

> v123：请求体 `script_id` → `strategy_id`；sweep 改 batch 语义 + best 回写；实盘门禁。引擎细节见 [`strategy-exec/spec.md`](../strategy-exec/spec.md) REQ-SE-002/008/009。

- 引擎在 strategy_exec（只算不算单，共享单库）；EvTrade 转发层带 `strategy_id`
- 回测：单次=1 行 task；扫描=1 批次 N 行 task；批次完成后 strategy_exec 按 batch 算 best → 覆盖 `strategy.best_params`
- 实盘：`mode=live`、`params=strategy.best_params`；无回测禁止启动（NO_BEST_PARAMS）
- 审计：strategy_exec 写 `strategy_script_audit(task_id)`
- `live_signals` 环形缓冲（限 500，5s flush）由 LiveRunner 实现，不变

#### Scenario: 单次回测后回写 best

- **WHEN** 单次回测（1 行 task）完成
- **THEN** 该 task 的 params 即为该 batch best，覆盖 `strategy.best_params`

#### Scenario: 扫描部分失败仍回写 best

- **WHEN** 批次 16 组合中 2 组合失败
- **THEN** 该 2 task `status='failed'`，其余 finished；best 从 14 个成功的里挑并覆盖 `strategy.best_params`

#### Scenario: 全失败不回写 best

- **WHEN** 批次全部组合失败
- **THEN** `strategy.best_params` 保持原值不被清空

### REQ-STRAT-017: 前端 2 个 view + 14 端点客户端

- **`client/src/views/ScriptDev.vue`** — 策略开发页（脚本库）：写代码 + params_schema；保存后"去创建策略"跳 ScriptTask
- **`client/src/views/ScriptTask.vue`** — 策略运行页：
  - 顶部选策略（或新建策略 {name, script_id}）
  - **单次回测**：展示全部参数（按 schema 类型渲染，默认值=default）
  - **参数扫描**：int/float 显示起止+步长（默认带出 min/max/step，可调）；choice 显示逗号分隔值列表（可调）；string 固定值不参与扫描
  - **批次列表 + 任务表格**：前几列=参数（动态列，按 schema 类型格式化）、后几列=结果（pnl/回撤/胜率/交易数等）；点击行 → 下方详情（backtest_result 图表/信号/audit）
  - **实盘启动**：`best_params` 为空 → 提示"请先回测生成最优参数"；成功 → 建实盘批次并显示"实盘"徽章
  - 订阅 ws `task_progress_update` 实时刷新进度
- 客户端封装：`client/src/api/script_strategy.js`

#### Scenario: 扫描表单按类型渲染

- **WHEN** 策略脚本 schema 含 `int(fast)` 与 `choice(entry_signal)`
- **THEN** `fast` 显示起止+步长输入；`entry_signal` 显示逗号分隔值列表输入

#### Scenario: 批次表格动态参数列

- **WHEN** 打开某回测批次
- **THEN** 表格前几列 = 该脚本 schema 的参数 key（fast/slow/...），后几列 = 结果字段

#### Scenario: 实盘无 best 提示门禁

- **WHEN** 用户点"启动实盘"而策略 `best_params` 为空
- **THEN** UI 提示"请先回测生成最优参数"，不发起请求
