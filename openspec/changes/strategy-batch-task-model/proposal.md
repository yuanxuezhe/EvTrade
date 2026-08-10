# strategy-batch-task-model — 策略/批次/任务 三层模型重构

## Why

v122 用 `sweep_id/sweep_total/sweep_metric` 3 列 + summary task 表达扫描，但 summary task 是特例、`best_params` 落在 task 上、任务直接挂 `script_id`，导致"一个脚本建多个策略"、"回测后最优参数回写策略再跑实盘"这类需求要绕路。目标是引入显式 `strategy`（策略）层、用"批次 batch"统一单次回测/参数扫描/实盘启动，`best_params` 收敛到策略表，并让扫描表单按 `params_schema` 类型渲染。

## What Changes

- **BREAKING** `strategy_task` 不再挂 `script_id`，改挂新增 `strategy` 表的 `strategy_id`；`script_id` 列删除。
- **新增 `strategy` 表**（自增 id）：`strategy_id / user_id / script_id → strategy_script.id / name / status / best_params / created_at / updated_at`。一个脚本可被多个策略复用（脚本库 `strategy_script` 不动）。
- **新增 `batch_no`（批次号）**：序号表 `order_no_seq` 泛化为多生成器 `(seq_name PK, last_value)`，新增 `task_batch` 生成器；`strategy_id` / `task_id` 用 DB 自增（不走序号表）。
- **删除 `sweep_id / sweep_total / sweep_metric` 3 列** + summary task 特例，由 `batch_no` 统一表达"一次回测/实盘 = 一个批次（1..N 行 task）"。
- **`best_params` 移到 `strategy` 表**：每完成一个回测批次，按批次内 tasks 排序算 best，**直接覆盖** `strategy.best_params`（本期只存绩效最优参数，后续方案再扩展）。
- **实盘门禁**：启动实盘前校验 `strategy.best_params` 非空，否则拒绝并提示"请先回测生成最优参数"。
- **扫描表单按类型渲染**：`params_schema` 的 type 驱动——`int/float` 显示起止+步长（默认带出 min/max/step），`choice` 显示逗号分隔值列表，`string` 固定值不参与扫描。单次回测展示全部参数、默认值取 `default`。
- **结果表格 + 详情下钻**：批次任务表前几列 = 参数（按 schema 动态列），后几列 = 回测结果；点击行在下方展示该组参数的图表/信号等详情。
- **`params` 存储格式确认**：DB 存 JSON（API 层唯一读写入口），前端展示时按需拼 `key:value`。
- **实盘走批次**：实盘启动也建 1 个 batch（`mode='live'`，1 行 task），UI 加"实盘"徽章区分。

## Capabilities

### New Capabilities

（无新 capability；本改动落在既有 strategy / strategy-exec / data-model / frontend 四类能力上）

### Modified Capabilities

- `data-model`：新增 `strategy` 表；重构 `strategy_task`（script_id→strategy_id、加 batch_no、删 sweep 3 列、best_params 迁出）；`order_no_seq` 泛化为多生成器表（加 `task_batch`）。
- `strategy`：REQ-STRAT-014~017 全面调整——策略 CRUD（script_id 引用）、任务创建/批次启动/批次分析、best_params 回写策略、实盘门禁（无回测禁止实盘）。
- `strategy-exec`：引擎层任务关联从 script_id 改为 strategy_id；sweep 逻辑改为按 batch 组织 + 完成后回写 `strategy.best_params`；移除 summary task。
- `frontend`：ScriptTask.vue 改为"批次 + 任务表格"两段式 UI，扫描表单按类型渲染，实盘门禁提示，实盘徽章。

## Impact

- **DB 迁移**（新迁移脚本）：建 `strategy` 表；`strategy_task` 增 `strategy_id`/`batch_no`、删 `script_id`/sweep 3 列、删 `best_params`；`order_no_seq` 表结构变更（多生成器）；存量数据回填（每个 task 按 script_id 归属到策略，或先建默认策略再映射）。
- **后端**：`server/tables/`（strategy.py 新增 / strategy_task.py 重构 / order_no_seq.py 泛化）、`server/api/script_strategy/endpoints.py`、`server/services/strategy/`、序号服务 `order_no.py`（新增 `next_seq`）。
- **strategy_exec**：`data_access/strategy_task.py`、`engines/backtrader/sweep.py`（batch 化 + best 回写）、`api/internal.py`（run-sweep 语义调整）。
- **前端**：`client/src/views/ScriptTask.vue`、`client/src/components/strategy/`（SweepForm / SweepResultsTable / BacktestPicker 重写为批次+按类型表单）、`client/src/api/script_strategy.js`。
- **测试**：`tests/server/strategy/`、strategy_exec 单测；批次分析、best 覆盖、实盘门禁场景。
