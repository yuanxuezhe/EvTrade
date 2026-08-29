# frontend — Spec Delta (2026-08-29)

## 修改类型
MODIFIED — 新增 REQ-FE-538 ScriptTask 进度可视化 + trades 行可展开 + 轮询 fallback

## 变更内容

### § REQ-FE-538: ScriptTask 页进度可视化（新增）

ScriptTask 页 MUST 提供实时任务进度可视化，覆盖回测 4 阶段（load_script → build_cerebro → running → done）+ 老 queued 兜底轮询。

#### Scenario: 进度环可视化

- **GIVEN** user 打开 ScriptTask 页，选中 1 个 running 批次
- **WHEN** ws 推 1 条 `{task_id, status: 'running', progress: {phase: 'running', bar_idx: 42, total_bars: 240}}`
- **THEN** BatchTasksTable 对应行「状态」列显示：
  - 圆环 `<el-progress type="circle" :percentage="42/240*100">` + 文字 "42/240"
- **AND** 行 hover 0.5s 后 tooltip 显示 "回测中 bar=42/240"
- **WHEN** ws 推 `{status: 'finished', progress: {phase: 'done'}}`
- **THEN** 圆环变 `<el-tag type="success">完成</el-tag>`

#### Scenario: trades 行可展开 + tooltip

- **GIVEN** user 选中 1 个 finished task，进入 TaskDetail 详情
- **WHEN** 切到「交易明细」tab
- **THEN** trades 表头加 `type="expand"` 控制列
- **WHEN** user 点开某 1 行
- **THEN** 展开面板显示完整 signal JSON：
  - 触发原因（msg）
  - 指标（indicators key=value 列表）
  - 持仓变化（state.position 变化量）
  - 现金（state.cash 变化量）
  - 单号（order_no，如有）
  - stime / close / position / equity
- **AND** 列头 hover 显示 tooltip 提示该列含义

#### Scenario: 3s 轮询 fallback

- **GIVEN** user 打开 ScriptTask 页，选中 1 个 batch 含 queued/running task
- **WHEN** 页面 mount 后 3s 内 ws 未推 task_progress
- **THEN** 自动启动 3s 周期轮询 `loadBatches()` + `loadBatchTasks()`
- **AND** ws 推送与轮询并存（不互斥，节流刷新共用）
- **WHEN** 批次内所有 task 进入 finished/failed/stopped/abandoned
- **THEN** 自动停轮询
- **WHEN** user 切换 batch / 切换策略 / 卸载组件
- **THEN** 轮询 timer 清理

#### Scenario: 老 queued 任务视觉标记（轻量）

- **GIVEN** 批次内 task 卡 queued > 24h（started_at IS NULL 且 created_at 距今 ≥ 24h）
- **WHEN** 显示在 BatchTasksTable
- **THEN** 行加灰色背景 + 「已超时」tag（仅视觉提示，不改数据）
- **AND** 不主动删除 / 改 status（用户硬规则）

## 影响面
- `client/src/views/ScriptTask.vue` 加轮询逻辑（+20 行）
- `client/src/components/strategy/BatchTasksTable.vue` 状态列改 progress ring（+30 行）
- `client/src/components/strategy/TaskDetail.vue` trades 行可展开（+40 行）
- 零 store 变更
- 零 API 变更

## 不修改
- 不动 ws_dispatch.js / ws.js（payload 兼容）
- 不动 script_strategy.js API client
- 不动 Pinia store（仅用现有 wsStore.lastTaskProgress）
- 不动后端
- 不动 DB（用户硬规则）