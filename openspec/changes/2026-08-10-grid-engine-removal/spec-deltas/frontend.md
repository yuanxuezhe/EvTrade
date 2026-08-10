# spec-delta: frontend（现有 spec 增量）

## REMOVED Requirements

### REQ-FE-310: 策略交易路由 + 角色守卫（strategy_trade）— 已删除

> **变更说明（2026-08-10）**：commit `aa70dae` 删除了网格策略前端：`StrategyTrade.vue` / `AlgoStrategy.vue` / `useStrategyTrade.js` / `modules/strategy/(8)` / `components/strategy/StrategyList.vue` / `stores/strategy.js` / `api/strategy.js`，并清 `router` / `Sidebar` / `BottomNav` / `AppHeader` 中 `/strategy-trade` 入口 + `ws_heartbeat` 中 `strategy_update` 频道 + `ws_dispatch.js` 中 `_onStrategyUpdate` 分发。

REQ-FE-310 全部内容删除：

- ~~`/strategy-trade` 路由 + `StrategyTrade.vue` 主视图~~
- ~~`meta.requiresTrader` 角色守卫~~
- ~~`/algo-strategy` → `/strategy-trade` 旧路由重定向~~
- ~~`strategy_update` WS 频道 + `useStrategyStore().appendAudit` 分发~~
- ~~`Sidebar.vue` `/strategy-trade` 导航链接~~
- 关联 Scenario（trader 访问 /strategy-trade / 非 trader 重定向 / algo-strategy 重定向 / strategy_update WS 推送）全部删除

## 保留（未变）

- 脚本策略前端：`ScriptDev.vue` / `ScriptTask.vue` / `client/src/api/script_strategy.js`（现行，见 strategy/spec.md REQ-STRAT-017）
- 其余所有前端 REQ 不受影响
