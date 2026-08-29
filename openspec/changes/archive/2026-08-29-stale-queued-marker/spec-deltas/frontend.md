# frontend — Spec Delta (2026-08-29)

## 修改类型
MODIFIED — REQ-FE-546 增加 stale-queued 视觉标记场景

## 变更内容

### § REQ-FE-546 末尾追加 § Scenario: 老 queued 任务视觉标记（轻量）扩展

**原描述**：
> #### Scenario: 老 queued 任务视觉标记（轻量）
> - **GIVEN** 批次内 task 卡 queued > 24h（created_at 距今 ≥ 24h 且 started_at IS NULL）
> - **WHEN** 显示在 BatchTasksTable
> - **THEN** 行加灰色背景 + 「已超时」tag（仅视觉提示，不改数据；用户硬规则：禁清表数据）
> - **AND** 不主动删除 / 改 status

**扩展为完整实现规范**：

#### 判定逻辑

- task MUST 满足以下**全部**条件才标记 stale：
  1. `status === 'queued'`
  2. `started_at IS NULL`（从未被 strategy_exec 调度过）
  3. `progress IS NULL` 或 `progress.phase === 'queued'`
  4. `(now - created_at) >= 24 hours`

纯前端计算（无后端改动），`_isStaleQueued(row)` 函数返回布尔。

#### 视觉表现（BatchTasksTable.vue）

- 行加 `:class="{ 'bf-row-stale': isStaleQueued(row) }"`
- CSS:
  - `.bf-row-stale { background: var(--bg-secondary, #f7f8fa); opacity: 0.85; }`
  - `.bf-row-stale td { color: var(--text-secondary); }`
- 「状态」列 stale 时：
  - 保留原 `<el-tag size="small" type="info">排队中</el-tag>`
  - 追加 `<el-tag size="small" type="warning" effect="dark">已超时</el-tag>`
- 行 hover `<el-tooltip :show-after="500">` 显示 "卡 N 小时，建议重测或联系 admin"

#### 过滤功能（可选 UX）

- BatchTasksTable 顶部加 `<el-checkbox v-model="showStaleOnly">只看超时任务</el-checkbox>`
- 默认 false
- 勾选后 computed `filteredTasks` = `tasks.filter(isStaleQueued)`
- 表格 `:data` 绑 `filteredTasks`（替代直接 `tasks`）

#### 批次卡片顶部 banner（ScriptTask.vue）

- 批次列表 card 顶部条件显示 `<el-alert type="warning" :closable="true" :title="`批次内 ${staleQueuedCount} 个任务卡 queued > 24h，建议重测或联系 admin`" v-if="staleQueuedCount > 0">`
- computed `staleQueuedCount` = 当前 batchTasks.filter(isStaleQueued).length
- 仅当 ≥1 stale 时显示，可关闭（dismiss，session 内不重显）

#### 数据安全（用户硬规则 2026-08-27）

- 不动 MySQL 任何表/列/行
- 不 drop / truncate / delete from
- 不重建 schema，不跑 sync_schema.py apply
- 不主动 abandon / 改 status 老 task
- 视觉标记纯前端衍生，与 task_progress_update ws 推送解耦

### § Scenario: 后端 stale-queued 查询（admin-only）

- **GIVEN** admin 调 `GET /api/script-strategy/strategies/{strategy_id}/stale-queued`
- **WHEN** 该 strategy 存在 ≥1 stale queued task
- **THEN** 返 `200 {strategy_id, stale_count, stale_tasks: [{task_id, batch_no, age_min, created_at}]}`
- **WHEN** strategy 不存在或 stale_count=0
- **THEN** 返 `200 {strategy_id, stale_count: 0, stale_tasks: []}`
- **WHEN** 非 admin 用户调
- **THEN** 返 `403 FORBIDDEN`（不暴露给 owner 隐私）
- **AND** owner 也能在批次列表前端看到 stale 标记（不依赖此端点）

## 影响面

| 模块 | 影响 |
|---|---|
| client/src/components/strategy/BatchTasksTable.vue | +25 行（判定函数 + 模板分支 + CSS） |
| client/src/views/ScriptTask.vue | +15 行（banner + checkbox 联动） |
| server/services/script_strategy/batches.py | +20 行（list_stale_queued_tasks helper） |
| server/api/script_strategy/strategies.py | +25 行（端点 + schema） |
| server/tests/strategy/test_stale_queued.py | 新增（~80 行） |
| openspec/specs/strategy/spec.md | 补 stale 概念段（如果 § Script-Strategy 模块章节存在） |

## 不修改

- 不动 DB（用户硬规则）
- 不动 ws 推送逻辑
- 不动 strategy_exec 引擎
- 不动老 queued task 的 status