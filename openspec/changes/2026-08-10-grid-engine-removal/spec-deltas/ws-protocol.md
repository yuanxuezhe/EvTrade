# spec-delta: ws-protocol（现有 spec 增量）

## REMOVED Requirements

### strategy_update 策略频道 — 已删除

> **变更说明（2026-08-10）**：commit `aa70dae` 删除网格策略引擎，`strategy_update` 频道已从 `ws_manager.active_connections` 移除，`server/services/strategy/engine.py`（唯一推送方）已删。`t0_strategy_update`（T0 策略引擎 `t0/engine.py`）也已随引擎删除。

删除以下引用：

- ~~第 9 行 "1 个策略 channel（strategy_update）"~~
- ~~第 13 行 `t0_strategy_update` 频道注（t0/engine.py:42）~~
- ~~第 34 行 `/ws/strategy_update` 订阅表行~~
- ~~第 53 行 event 枚举 `regime_changed | grid_triggered | regime_cooldown`~~
- ~~第 56 行 channel 清单中的 `strategy_update`~~
- ~~第 72 行 `strategyStore.applyEvent(...)` 分发行~~
- ~~第 177 行 🟡 `t0_strategy_update` 未注册待办~~

## MODIFIED Requirements

### 频道总数与分类

- "7 个 channel" 相关描述更新：当前 `ws_manager.active_connections` 注册 **6 频道**（`order_update` / `trade_update` / `position_update` / `quote_update` / `system_update` / `task_progress_update`）
- 分类描述移除"策略 channel"类别（网格策略已下线；脚本策略进度走 `task_progress_update`）

## 保留（未变）

- 其余 6 频道协议（订阅 / 心跳 / payload schema）
