# ws-protocol — Spec Delta (2026-08-29)

## 修改类型
MODIFIED — REQ-WS-002 payload 协议 `task_progress_update` 字段细化

## 变更内容

### § REQ-WS-002 payload 协议 — task_progress_update 数据流扩展

**Before**:
> `task_progress` (task_progress_update channel) | `scriptTaskStore.updateProgress(...)`

**After**:
> `task_progress` (task_progress_update channel) | `useWsStore().lastTaskProgress = {ts, ...row}` → `ScriptTask.vue` watch 节流刷新批次表格 + 就地更新 detail.progress

#### payload schema (扩展 progress.phase 取值)

```json
{
  "type": "task_progress",
  "channel": "task_progress_update",
  "ts": "<ISO 时间>",
  "data": {
    "task_id": 14,
    "status": "running" | "finished" | "failed" | "stopped",
    "progress": {
      "phase": "load_script" | "build_cerebro" | "running" | "live_running"
              | "writing_result" | "done" | "failed" | "stopped" | "queued",
      "msg": "<str, 描述当前阶段>",
      "bar_idx": 42,
      "total_bars": 240,
      "current": 3,
      "total": 4,
      "updated_at": "<ISO 时间>"
    }
  }
}
```

#### 触发源（变化）

**Before**: 仅 `signal_consumer._broadcast_task_progress`（signal 流到达时推）

**After**: 2 个触发源
1. `signal_consumer._broadcast_task_progress` — 信号流触发（live task BUY/SELL/INFO 信号时推，保留 v91.4 起旧语义）
2. `server/services/strategy/task_progress_consumer` — task phase 变化触发（回测 4 阶段 + status 转换）

#### Scenario: 回测全程推送

- **GIVEN** 4 组合 sweep batch 提交到 strategy_exec
- **WHEN** strategy_exec 跑完第 1 个 task 全流程
- **THEN** 前端 ws task_progress_update 频道收到 ≥ 4 条推送：
  - `{status: 'running', progress: {phase: 'load_script'}}`
  - `{status: 'running', progress: {phase: 'build_cerebro'}}`
  - `{status: 'running', progress: {phase: 'running', bar_idx: N/total_bars}}` （按 5%/2s 节流）
  - `{status: 'finished', progress: {phase: 'writing_result' 或 'done'}}`
- **AND** ScriptTask.vue 节流刷新批次表格，对应行 status tag 从「排队中」→「运行中」→「完成」
- **AND** 详情面板 progress bar 显示 N/total_bars

#### Scenario: 老 queued 任务无推送

- **GIVEN** 老 batch task status='queued' 长期未起
- **WHEN** 前端订阅 ws task_progress_update
- **THEN** 收不到该 task 任何推送（status='queued' 在 publisher 跳过）
- **AND** 前端通过 REST `/api/script-strategy/tasks/{id}` 查得 status='queued'
- **AND** 批次表格显示「排队中」tag（已有行为）

## 影响面
- 前端 ws_dispatch.js `_onTaskProgress` 不变（payload 兼容）
- 前端 ScriptTask.vue watch 逻辑不变（兼容 payload 扩展）
- 后端 signal_consumer._broadcast_task_progress 不变（旧路径保留）
- 后端新增 task_progress_consumer（独立模块）
- ws_manager.broadcast 调用者从 1 处变 2 处

## 不修改
- 不动 channel 列表（仍是 7 个）
- 不动 type enum（task_progress 已含）
- 不动 ws_manager 接口
- 不动前端 _onTaskProgress 路由（兼容新 payload 字段）