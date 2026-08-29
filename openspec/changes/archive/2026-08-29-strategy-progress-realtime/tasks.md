# Tasks: strategy-progress-realtime (2026-08-29)

> 每个 task = 1 个 commit（v6 单 commit 单目的）。
> 整体按 P0→P1→P2→P3 顺序推进，P2/P3 是文档收尾。

## P0 — 实时进度推送（核心）

- [ ] **commit 1 — strategy-exec publisher + hook**
  - 新文件 `strategy_exec/strategy_exec/signal/task_progress_publisher.py`
    - `class TaskProgressPublisher`：复用 signal_publisher 的 aio_pika connection，单例
    - `publish(task_id, status, progress)` async → RabbitMQ exchange `strategy.exchange`，routing_key `task.progress.{task_id}`
    - 节流（自维护 `_last_emit[task_id]`，phase 变化必推，否则 `bar_idx` 增量 ≥ 5% 或距上次 ≥ 2s 才推）
    - payload schema: `{type: "task_progress_update", task_id, status, progress, ts}`
  - 改 `strategy_exec/strategy_exec/data_access/strategy_task.py`:
    - `update_task_progress()` 写 DB 后调 `_emit_progress(task_id, status=None, progress=progress)`
    - `update_task_status()` 写 DB 后调 `_emit_progress(task_id, status=status, progress=None)`
    - status='queued' 跳过（无意义）
    - 抽 `_emit_progress()` 函数集中节流
  - 改 `strategy_exec/strategy_exec/signal/__init__.py` export `get_task_progress_publisher()`
  - 改 `strategy_exec/strategy_exec/main.py` startup 调 publisher.connect()，shutdown 调 close

- [ ] **commit 2 — server 端 consumer**
  - 新文件 `server/services/strategy/task_progress_consumer.py`
    - 复用 aio_pika connection 模式（与 signal_consumer 对称）
    - 订阅 routing_key `task.progress.*`，queue `EvTrade.TaskProgress`，durable
    - 收到消息 → `ws_manager.broadcast("task_progress_update", payload)`
    - payload 结构：与 publisher 一致（不重新包装，避免冗余）
  - 暴露 `start_task_progress_consumer()` / `stop_task_progress_consumer()`

- [ ] **commit 3 — main.py 启停钩子**
  - 改 `server/main.py`：startup 调 `start_task_progress_consumer()`；shutdown 调 `stop_task_progress_consumer()`
  - 与 signal_consumer 启停逻辑对齐（错峰启动，错峰停止）

- [ ] **commit 4 — server 单测**
  - 新文件 `server/tests/strategy/test_task_progress_consumer.py`
  - monkeypatch `ws_manager.broadcast` 收集 calls
  - 测：消费 1 条消息 → broadcast 1 次（payload 与 publish 一致）
  - 测：payload 含 type / task_id / status / progress 字段
  - 测：JSON 解析失败 → ack + skip（不抛异常）
  - 基线: `pytest server/tests/strategy/test_task_progress_consumer.py -v`

- [ ] **commit 5 — strategy-exec 节流单测**
  - 新文件 `strategy_exec/strategy_exec/tests/test_progress_throttle.py`
  - 测节流逻辑（用 fake clock）：
    - phase 变化 → 立即推
    - bar_idx < 5% 增量 → 跳过
    - bar_idx ≥ 5% 增量 且 < 2s → 跳过
    - bar_idx ≥ 5% 增量 且 ≥ 2s → 推
  - 测 status='queued' 跳过
  - 基线: `uv run pytest strategy_exec/strategy_exec/tests/test_progress_throttle.py -v`

## P1 — 前端可视化

- [ ] **commit 6 — 前端进度展示**
  - `client/src/components/strategy/BatchTasksTable.vue`:
    - status='running' 时「状态」列改显示 `<el-progress :percentage="...">` 圆环 + "N/total bars"
    - 行加 `<el-tooltip>` 显示 progress.phase + msg
  - `client/src/views/ScriptTask.vue`:
    - 加 3s 轮询 fallback（当前批次有 queued/running 时启动，全部完成停）
    - 卸载清 timer
  - `client/src/components/strategy/TaskDetail.vue`:
    - 「交易明细」tab 改 `<el-table type="expand">`
    - 展开行显示完整 signal JSON（msg/indicators/state/order_no）
    - 列加 tooltip（hover 0.5s delay）
  - 编译: `cd client && npm run build` 无报错

## P2 — spec 同步 + 知识库

- [ ] **commit 7 — spec-deltas 合并到 specs**
  - `openspec/specs/strategy-exec/spec.md`: 加 REQ-SE-012 (task_progress 实时推送)
  - `openspec/specs/ws-protocol/spec.md`: REQ-WS-002 payload `task_progress_update` 字段细化（progress.phase 包含 load_script/build_cerebro/running/done）
  - `openspec/specs/frontend/spec.md`: 加 REQ-FE-538 (ScriptTask 进度可视化 + trades 行可展开 + 轮询 fallback)
  - 归档 `mv openspec/changes/2026-08-29-strategy-progress-realtime openspec/changes/archive/`
  - 同步 `知识库/策略服务/信号推送.md`

## P3 — 老 queued 任务标记 (后续批次，本 change 不动)

- 用户拍板后另开 change。
- 不在本 tasks.md 范围。

## 验证（v6 完成自查）

- [ ] pytest server/tests/strategy/test_task_progress_consumer.py → 0 fail
- [ ] pytest strategy_exec/strategy_exec/tests/test_progress_throttle.py → 0 fail
- [ ] pytest server/tests/ → 58/58/0 基线不退化
- [ ] cd client && npm run build → 无报错
- [ ] git diff --stat 每 commit 单目的
- [ ] 不动 MySQL 任何表/列/行