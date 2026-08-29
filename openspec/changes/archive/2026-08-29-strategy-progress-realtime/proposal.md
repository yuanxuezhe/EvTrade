# Strategy Task Progress Realtime — 提案 (2026-08-29)

> 用户拍板 2026-08-29：按 P0→P1→P2→P3 顺序。
> 解决 ScriptTask 页"任务一直排队中"无法看到进度的卡死感；同步增强 trades 详情可读性。

## Why

**实测现场**（2026-08-29 SQL 查 strategy_task）：

| id | sid | batch  | status  | age_min | started | finished | progress |
|----|-----|--------|---------|---------|---------|----------|----------|
| 14 | 12  | 10000009 | queued | 8540  | None | None | None |
| 6  | 5   | 10000001 | queued | 11060 | None | None | None |
| 5  | 3   | 10000004 | queued | 19174 | None | None | None |
| 4  | 3   | 10000003 | queued | 24553 | None | None | None |
| 3  | 3   | 10000002 | queued | 24553 | None | None | None |

**结论**：5 条任务全部 `status='queued'` 永远不动；`started_at=None`、`progress=None`、`finished_at=None`。ScriptTask 页只看到「排队中」tag，看不到任何进度反馈。

**根因链路**（已逐段读代码）：

```text
strategy_exec/engines/backtrader/backtest.py:
  update_task_progress(task_id, {"phase": "load_script", "current": 1, "total": 4})   # L109
  update_task_progress(task_id, {"phase": "build_cerebro", "current": 2, "total": 4})  # L126
  update_task_progress(task_id, {"phase": "running", "current": 3, "total": 4})       # L154
  → 全部只写 strategy_task.progress 字段，从不广播到 WS

server/services/strategy/signal_consumer.py:_broadcast_task_progress (L226):
  只在 RabbitMQ signal 流到达时（即用户脚本 buy_signal/sell_signal 触发时）广播
  payload: {task_id, status, progress: {phase: 'live_running', ...}}
  → phase='load_script/build_cerebro/running/done' 从未经过此函数
```

**总结**：`task_progress_update` WS 频道**只在有 signal 到达时**才有消息；**回测过程中用户看不到任何 phase 变化**；老 queued 任务**根本没起来过**（EvTrade 提交即转发，2xx 才算提交成功；若 RabbitMQ 不可达或 his_hq 超时，task status 不会被 strategy_exec 改写，永久卡 queued）。

**用户影响**：
- 用户看不到"加载脚本→构造引擎→回测中（N/total bars）→完成"全流程
- 即使回测成功，前端也要等下一次 ws 推或主动刷新才能感知
- 老孤儿任务无可视化标记

## What

### P0 — 实时进度推送（核心修复）

1. **strategy_exec 加本地 task_progress publisher**
   - 新文件 `strategy_exec/strategy_exec/signal/task_progress_publisher.py`
   - 复用同一 RabbitMQ exchange `strategy.exchange`（或新 exchange `task.progress`，TBD 在实施期定）
   - routing_key = `task.progress.{task_id}`，topic
   - 与 signal publisher 共用一个 connection（避免重复 connect）
   - 节流：phase 变化立刻推；`running.bar_idx` 增量按 5%/2s 节流（最小间隔 2s）

2. **`update_task_progress()` / `update_task_status()` 加 hook**
   - 写 DB 成功后调本地 publisher.publish({task_id, status, progress})
   - 抽公共函数 `_emit_progress(task_id, status, progress)` 集中节流
   - 跳过 status='queued'（无意义）+ 跳过 progress 为空（与旧版兼容）

3. **EvTrade 端加 consumer**
   - 新文件 `server/services/strategy/task_progress_consumer.py`
   - 订阅 routing_key `task.progress.*`
   - 收到消息 → `ws_manager.broadcast("task_progress_update", {type: "task_progress_update", task_id, status, progress})`
   - 同 ws_manager 现有契约，零侵入
   - 启停：在 `server/main.py` 启停钩子对称处理（与 signal_consumer 一致）

4. **测试覆盖**
   - `server/tests/strategy/test_task_progress_consumer.py` — 节流 + 解析 + ws broadcast fake
   - `strategy_exec/strategy_exec/tests/test_progress_throttle.py` — 节流逻辑（5%/2s）

### P1 — 前端可视化增强

1. **BatchTasksTable 加进度环 / 进度条列**
   - status=running 时显示 `<el-progress :percentage="...">` 圆环或条
   - 其它状态：原 tag
   - 全部 task 行加 hover tooltip 显示 `progress.phase + msg + bar_idx/total_bars`

2. **TaskDetail.vue trades 行可展开**
   - `<el-table>` 加 `type="expand"`
   - 展开行：完整 signal JSON（msg / indicators / state.position / state.cash / order_no / stime）
   - 列头也加 hover tooltip 显示核心字段说明

4. **ScriptTask.vue 加轮询 fallback**
   - 检测当前 batch 有 `queued|running` 状态 task → 启动 3s 轮询 `loadBatches` + `loadBatchTasks`
   - 全部 finished/failed/abandoned → 停轮询
   - ws 推到来 → 节流刷新逻辑保持，轮询不停（互不冲突）
   - 卸载组件时清 timer

### P2 — 文档同步

- `openspec/specs/strategy-exec/spec.md` 加 REQ-SE-012 (task_progress 实时推送)
- `openspec/specs/ws-protocol/spec.md` REQ-WS-002 payload `task_progress_update` 改写（明确包含 phase=load_script/build_cerebro/running/done）
- `openspec/specs/frontend/spec.md` 加 REQ-FE-538 (ScriptTask 进度可视化 + trades 行可展开)
- `知识库/策略服务/信号推送.md` 同步新机制
- `知识库/前端/strategy.md`（如有）同步

### P3 — 老 queued 任务标记

- 不主动改老任务（用户硬规则：禁清数据）
- 前端批次列表给"任务卡 > 24h"加视觉标记（淡灰 + "已超时" tag），不删除
- 这是 P3 单独批次，按 P0/P1 跑稳后再做

## 不做什么

- 不动 MySQL 任何表/列/行（用户硬规则 2026-08-27）
- 不 drop / truncate / delete from
- 不重建 schema，不跑 sync_schema.py apply
- 不改 RabbitMQ 拓扑结构（exchange/queue 名）（用户拍板：复用 strategy.exchange + 新 routing_key，零迁移成本）
- 不动 signal_consumer 的 `_broadcast_task_progress`（仅在有 signal 时推，仍保留其语义；新机制独立通道）
- 不改策略算法逻辑（不重构 run_backtest）

## 影响面

| 模块 | 影响 |
|---|---|
| strategy_exec/data_access/strategy_task.py | update_task_progress/status 加 hook |
| strategy_exec/signal/ | 新增 task_progress_publisher.py + __init__.py export |
| strategy_exec/main.py | 启动时 connect task_progress publisher；停止时 close |
| server/services/strategy/ | 新增 task_progress_consumer.py |
| server/main.py | startup/shutdown 钩加 consumer 启停 |
| client/src/views/ScriptTask.vue | 节流刷新逻辑保留 + 加 3s 轮询 fallback |
| client/src/components/strategy/BatchTasksTable.vue | 列加进度环 / tooltip |
| client/src/components/strategy/TaskDetail.vue | trades 行可展开 + tooltip |
| openspec/specs/strategy-exec/spec.md | + REQ-SE-012 |
| openspec/specs/ws-protocol/spec.md | payload 协议细化 |
| openspec/specs/frontend/spec.md | + REQ-FE-538 |
| 知识库/策略服务/信号推送.md | 同步 |

## Commit 拆解 (v6)

```
1. feat(strategy-exec): task_progress_publisher + update_* hook (策略服务单进程内)
2. feat(server): task_progress_consumer (RabbitMQ → ws_manager broadcast)
3. feat(server): main.py 启停 consumer
4. test(server): task_progress_consumer 节流 + 解析 + ws broadcast fake
5. test(strategy-exec): progress 节流单测
6. feat(client): ScriptTask.vue 轮询 fallback + BatchTasksTable 进度环 + TaskDetail trades 展开
7. docs(openspec): strategy-exec / ws-protocol / frontend spec-delta + merge
```

## 数据安全（用户硬规则 2026-08-27）

- [ ] 不动 MySQL 任何表/列/行
- [ ] 不 drop / truncate / delete from
- [ ] 不重建 schema，不跑 sync_schema.py apply

## 验证

- [ ] pytest server/tests/strategy/test_task_progress_consumer.py 0 fail
- [ ] pytest strategy_exec/strategy_exec/tests/test_progress_throttle.py 0 fail
- [ ] pytest server/tests/ → 基线 58/58/0 不退化
- [ ] cd client && npm run build → 无报错
- [ ] 实测：新建一个 4 组合 sweep batch → 看到 phase='load_script/build_cerebro/running/done' 全程推送到前端
- [ ] git diff --stat 每 commit 单目的