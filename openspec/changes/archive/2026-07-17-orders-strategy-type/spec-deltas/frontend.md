## ADDED Requirements

### REQ-FE-530: strategy_type 前端 UI 透传 + 缓存展示（v66 NEW）

**业务定位**: 前端展示 strategy_type 字段，让用户/admin 看到单子的策略类型分类。

**改动点**:
1. **`Trade.vue` 普通单** (`client/src/views/Trade.vue::handleOrderSubmit`):
   - 在 `orderStore.placeOrder(orderData)` 前注入 `strategy_type: 0`
   - 与 Pydantic Literal[0,1] default 0 对齐；显式传避免隐式默认被未来默认值改动影响

2. **`T0Trade.vue` 快速做T** (`client/src/views/T0Trade.vue::_submitOrder`):
   - payload 加 `strategy_type: 1` 字段（与 user_def='T0' 共存）
   - 与 v18 task_id 字段同层透传

3. **`orderCalc.js metaMerge`** (`client/src/utils/orderCalc.js`):
   - 透传 strategy_type 字段（与 v65 task_id 同模式）
   - `row.strategy_type ?? ref.strategy_type ?? 0` 写回 merged
   - 防 `_upsertToHoldings → applyOrderPush → metaMerge` 丢 strategy_type（与 task_id 同类 bug 模式）

4. **`CacheOrders.vue` 缓存表** (`client/src/views/CacheOrders.vue`):
   - fields 加 `{ key: 'strategy_type', label: '策略类型', type: 'number', width: 110 }`
   - 紧跟 task_id 列；admin 在 `/admin/cache/orders` 可视化所有单的 strategy_type

5. **`TodayOrdersPanel.vue` 委托表** (`client/src/components/trade/TodayOrdersPanel.vue`):
   - 加 "策略" 列（紧跟 task_id 列）:
     - `Number(row.strategy_type) === 1` → `el-tag type="danger" size="small"` "做T"
     - 否则 → `span class="text-muted"` "普通"
   - 与 status/order_type chip 同视觉风格

**未改 (后续候选)**:
- T0Trade.vue 委托明细 filter 当前仍用 `o.user_def === 'T0'` 字符串过滤；改 `o.strategy_type === 1` 是 v67 候选（向后兼容 user_def 后再切换）
- metaMerge 自动化单测（v65 补过 task_id 单测可借鉴，本 PR 浏览器实测一并验证）

#### Scenario: Trade.vue 下单后缓存 strategy_type=0

- **GIVEN** user 在 `/trade` 填单 → 点"确认买入"
- **WHEN** `orderStore.placeOrder(payload)` POST 后响应回包 + WS push
- **THEN** `holdings.orders` 中该行 `strategy_type = 0`
- **AND** `/trade` 页面 `TodayOrdersPanel` "策略" 列显示 "普通"（灰色）

#### Scenario: T0Trade.vue 下单后缓存 strategy_type=1

- **GIVEN** user 在 `/t0-trade` → 点"确认做T"
- **WHEN** `orderStore.placeOrder(payload)` POST 后响应回包 + WS push
- **THEN** `holdings.orders` 中该行 `strategy_type = 1` AND `user_def = 'T0'`
- **AND** `/trade` 页面 `TodayOrdersPanel` "策略" 列显示 "做T"（红色 el-tag）

#### Scenario: admin 缓存页 strategy_type 列展示

- **GIVEN** admin role
- **WHEN** navigate `/admin/cache/orders`
- **THEN** el-table MUST 渲染 "策略类型" 列
- **AND** 行 strategy_type 值显示为 number（0/1）
- **AND** 可与 task_id 列联动分析（task_id IS NOT NULL ⇒ strategy_type=1, 反之不一定）

#### Scenario: metaMerge 透传兜底

- **GIVEN** v66 之前的历史单 (ref.strategy_type = undefined, row.strategy_type = undefined)
- **WHEN** `_upsertToHoldings(order)` → `applyOrderPush` → `metaMerge(row, ref)`
- **THEN** merged.strategy_type = 0（兜底）
- **AND** TodayOrdersPanel 仍正确显示 "普通" chip（不显示 undefined）
