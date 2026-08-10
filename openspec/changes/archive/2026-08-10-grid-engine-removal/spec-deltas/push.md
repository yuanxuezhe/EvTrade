# spec-delta: push（现有 spec 增量）

## REMOVED Requirements

### REQ-PUSH-040: strategy_update 频道（strategy_trade）— 已删除

> **变更说明（2026-08-10）**：commit `aa70dae` 删除了网格策略引擎。`strategy_update` 频道已从 `server/ws/manager.py::WSManager.active_connections` **移除**（当前注册 6 频道：`order_update` / `trade_update` / `position_update` / `quote_update` / `system_update` / `task_progress_update`），`engine.py::_broadcast()` 已删。

REQ-PUSH-040 全部内容删除：

- ~~`STRATEGY_WS_CHANNEL = "strategy_update"` 频道注册~~
- ~~payload schema（regime_changed / grid_triggered / regime_cooldown 事件）~~
- ~~Scenario: strategy_update 缺 strategy_id 静默丢弃~~

## MODIFIED Requirements

### 频道清单类引用（344 / 358 / 363 / 368 行附近）

- 344 行 `同时新增 strategy_update（v66）/ system_update（v117）/ task_progress_update（v91.4）` → 移除 `strategy_update（v66）` 引用
- 358 行 `strategy_update` 来源行（`engine.py::_broadcast()`）→ 删除（引擎已删）
- 363 行 `t0_strategy_update` 频道注（`t0/engine.py:42` 常量）→ 删除（t0 引擎已删）
- 368 行 `active_connections 必须包含所有 key` 清单 → 移除 `strategy_update`

## 保留（未变）

- 其余 push 频道（order_update / trade_update / position_update / quote_update / system_update / task_progress_update）
- REQ-PUSH-041 / REQ-PUSH-042（system_update / task_progress_update）
