# strategy-exec — Spec Delta (2026-08-29)

## 修改类型
MODIFIED — 新增 REQ-SE-012 task_progress 实时推送通道

## 变更内容

### § REQ-SE-012: task_progress 实时推送 (新增)

strategy_exec MUST 在 task phase / status 变化时通过 RabbitMQ 实时推送到 EvTrade，由 EvTrade 端 consumer 广播到 `task_progress_update` WS 频道。

**Why**：当前 `_broadcast_task_progress` 只在 signal 流到达时触发，回测过程中用户看不到 load_script / build_cerebro / running / done 任何阶段变化，UX 卡"排队中"无反馈。

#### 链路

```text
strategy_exec 进程内:
  run_backtest() / LiveRunner.next() / sweep engine
    ↓ 调 update_task_progress(...) / update_task_status(...)
  data_access/strategy_task.py:_emit_progress(task_id, status, progress)
    ↓ 集中节流（phase 变化必推；bar_idx ≥ 5% 增量 且 ≥ 2s 距上次 推；status='queued' 跳过）
  signal/task_progress_publisher.py:TaskProgressPublisher.publish()
    ↓ exchange="strategy.exchange" routing_key="task.progress.{task_id}" payload=JSON
  RabbitMQ broker

EvTrade 进程内:
  server/services/strategy/task_progress_consumer.py
    ↓ 订阅 queue="EvTrade.TaskProgress" routing_key="task.progress.*"
  ws_manager.broadcast("task_progress_update", payload)
    ↓
  前端 ws task_progress_update 频道 → ws_dispatch.js _onTaskProgress()
    ↓
  useWsStore().lastTaskProgress = {ts, task_id, status, progress}
  ScriptTask.vue watch 节流刷新批次表格 + 就地更新 detail.progress
```

#### payload schema（RabbitMQ 消息体）

```json
{
  "type": "task_progress_update",
  "task_id": 14,
  "status": "running",
  "progress": {
    "phase": "running",
    "msg": "回测中 bar=42/240",
    "bar_idx": 42,
    "total_bars": 240,
    "current": 3,
    "total": 4,
    "updated_at": "2026-08-29T12:34:56.789"
  },
  "ts": "2026-08-29T12:34:56.789012"
}
```

#### 节流规则

| 条件 | 推送 |
|---|---|
| `status` 变化 (queued→running / running→finished/failed/stopped) | ✅ 立即推 |
| `progress.phase` 变化 (load_script→build_cerebro→running→done) | ✅ 立即推 |
| `progress.bar_idx` 增量 ≥ 5% 且距上次 ≥ 2s | ✅ 推 |
| `progress.bar_idx` 增量 < 5% 或距上次 < 2s | ❌ 跳过 |
| `status='queued'` | ❌ 跳过（无意义）|
| `progress is None` 且 status 未变 | ❌ 跳过 |

#### 数据源约束

- 共享 RabbitMQ broker（`EVTRADE_RABBITMQ_URL`）
- 共用 `strategy.exchange`（durable, topic）— 避免新增 exchange 拓扑
- routing_key 命名空间 `task.progress.*`（与 signal 路由 `stock_code` 命名空间隔离）
- queue `EvTrade.TaskProgress`（durable，EvTrade 端 consumer 独占）
- 复用 signal_publisher 的 aio_pika connection（单连接多 exchange / routing_key）

#### Scenario: 回测 4 阶段全程推送

- **GIVEN** user 提交 4 组合 sweep batch
- **WHEN** strategy_exec 跑第 1 个组合 task
- **THEN** RabbitMQ 收到 4 条消息（4 个 phase 变化）：load_script → build_cerebro → running → done
- **AND** 每条 message 5s 内被 consumer ack
- **AND** 前端 ws task_progress_update 收到 4 条推送
- **AND** ScriptTask.vue 批次表格内对应行 status 从 queued → running → finished

#### Scenario: bar_idx 节流

- **GIVEN** task 状态 running，bar_idx=100/240，距上次推 0.5s
- **WHEN** strategy_exec 写 progress bar_idx=110/240（增量 4.2%，< 5%）
- **THEN** 跳过推送
- **WHEN** bar_idx=112/240（增量 5%，但距上次 0.8s，仍 < 2s）
- **THEN** 跳过推送
- **WHEN** bar_idx=120/240（增量 ~9%，且距上次 ≥ 2s）
- **THEN** 推送 payload 含 bar_idx=120

#### Scenario: 老 queued 任务不推

- **GIVEN** task status='queued'，started_at=None，progress=None
- **WHEN** strategy_exec update_task_status('queued')（如 sweep batch 预建 task 时）
- **THEN** publisher 跳过，不发 RabbitMQ 消息
- **AND** 前端 ws 不收到消息

### § REQ-SE-002 增补：Internal endpoints 不变

`/internal/*` 不动；新机制走 RabbitMQ，与 `/internal/tasks/{task_id}/progress` (POST) 并行（HTTP 旧路径保留，零侵入）。

### § REQ-SE-003 增补：Backtrader 引擎调用 update_* 不变

`run_backtest()` 内的 update_task_progress 调用点不动；publisher hook 在 data_access 层透明接入，引擎代码零修改。

## 影响面
- 新增 `signal/task_progress_publisher.py` (~80 行)
- 新增 `tests/test_progress_throttle.py` (~60 行)
- 修改 `data_access/strategy_task.py` +30 行（_emit_progress 函数）
- 修改 `main.py` +5 行（startup/shutdown）
- 修改 `signal/__init__.py` export +1 行
- 零 schema 变更 / 零 DB 变更 / 零 queue 拓扑变更（仅新增 routing_key 命名空间 + queue 名 + 复用现有 exchange）

## 不修改
- 不动 RabbitMQ broker 拓扑（exchange 不新增）
- 不动 signal_consumer 的 `_broadcast_task_progress`（保留 signal 流触发语义）
- 不动策略算法（run_backtest / sweep / live runner）
- 不动 DB（用户硬规则 2026-08-27）