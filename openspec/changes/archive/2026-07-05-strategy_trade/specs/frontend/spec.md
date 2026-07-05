## ADDED Requirements

### Requirement: 策略交易视图与路由守卫（REQ-FE-300）

`client/src/router/index.js` MUST 新增路由 `/strategy-trade` 指向 `client/src/views/StrategyTrade.vue`，meta.roles = `['trader', 'admin']`。导航栏（`Sidebar.vue` 或等价组件）MUST 在「交易」分组下加入口「策略交易」。

#### Scenario: trader / admin 访问 /strategy-trade

- **WHEN** 已登录 user 的 role ∈ {trader, admin}
- **THEN** 渲染 StrategyTrade.vue 主视图

#### Scenario: 普通 user 访问被拒

- **WHEN** 已登录 user 的 role='user'
- **THEN** router 守卫拦截，redirect 到 /403 或登录页（沿用既有 RBAC 守卫实现）

#### Scenario: 导航栏入口仅 trader / admin 可见

- **WHEN** 普通 user 渲染 Sidebar
- **THEN** 「策略交易」入口 MUST NOT 渲染（条件渲染 role 守卫）

### Requirement: WS 频道 strategy_update 客户端处理（REQ-FE-301）

`client/src/stores/ws.js` MUST 注册 `strategy_update` 频道处理：收到消息 → `useStrategyStore().applyEvent(payload)` 更新对应 strategy 的 audit 列表 + 当前 regime。

#### Scenario: 收到 grid_triggered 事件

- **WHEN** WS 收到 `{type: 'grid_triggered', strategy_id: 5, order_no: '10000023', ...}`
- **THEN** strategy store MUST prepend 1 条 audit 到 strategy(id=5).audit 列表
- **AND** StrategyMonitor.vue MUST 自动 reactive 渲染新 audit 行（无需手动刷新）

#### Scenario: 收到 regime_changed 事件

- **WHEN** WS 收到 `{type: 'regime_changed', strategy_id: 5, from_regime_id: 3, regime_id: 5, ...}`
- **THEN** strategy store MUST 更新 strategy(id=5).current_regime_id = 5
- **AND** StrategyMonitor.vue MUST 显示新 regime name + 高亮切换动画（可选）