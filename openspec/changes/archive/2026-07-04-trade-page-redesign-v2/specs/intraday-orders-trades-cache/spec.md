## REMOVED Requirements

### Requirement: 独立 /today/orders 与 /today/trades 视图（v13 删除）

**Reason**：v13 起 `/today/orders` 与 `/today/trades` 路由删除（由 router redirect 指向 `/history/*`）。
当日委托 / 当日成交数据展示改由 `TodayOrdersPanel` / `TodayTradesPanel` 两个 mini-panel
组件**内嵌**到 `Trade.vue` 右侧 sticky 列，**不**作为独立路由 / 独立视图存在。

**数据契约不变**：mini-panel 与原 view 一样读 `useHoldingsStore().orders` / `.trades`（Pinia 内存 + IDB 持久化），
不走 `/api/orders` / `/api/trades` HTTP 拉取。ws 推送通过 `applyOrderPush` / `applyTradePush`
自动 merge 到 Pinia + IDB，panel 通过 Vue reactivity 自动更新。

**Migration**：
- 删 `client/src/views/TodayOrders.vue` 与 `client/src/views/TodayTrades.vue`
- 删 `client/src/router/index.js` 中 `/today/orders` `/today/trades` component 注册
- `router` 加 `/today/orders` `/today/trades` redirect → `/history/*` (老书签兼容)
- 现有 `client/src/components/trade/TodayOrdersPanel.vue` / `TodayTradesPanel.vue` 即承担旧 view 展示职责
  - 数据流同 v12: Pinia 内存读 → IDB 写穿透 → ws push 增量
  - 唯一区别: panel 是 mini 视图, 含分页, 不含独立页 banner / 汇总 / 日期过滤
- 用户视角: 打开 `/trade` 即看到今日委托 / 今日成交 (右侧 mini-panel)，无需再跳 `/today/*`

## ADDED Requirements

### Requirement: 今日委托 panel（TodayOrdersPanel 内嵌于 Trade.vue）

The system SHALL 提供 `client/src/components/trade/TodayOrdersPanel.vue` 组件，作为
`Trade.vue` 右侧 sticky 列的上方面板，承载今日委托数据的实时展示：

- **数据源**：`useHoldingsStore().orders`，Pinia 内存 + IDB write-through
- **范围过滤**（panel-local computed `todayOrders`）：
  - `trd_date === activeTrdDate`（仅当日）
  - `Number(order_flag) !== 1`（排除 cancel-row，统计口径干净）
- **分页**：el-pagination 默认 20 行/页 (pageSizes `[10, 20, 50, 100]`)，panel-local state，不入 Pinia
- **撤单按钮**：每行 `canCancel(row) === true` 时显示 `el-button type="danger" link size="small"` "撤"按钮
  - `canCancel(row)` 守卫 = `order_flag !== 1` AND `status` 不在 broker 终态集 `{51, 52, 53, 54, 55, 56, 57}`
  - 点击 → `ElMessageBox.confirm` 弹窗 → `orderStore.cancelOrder(row.order_no, row.trd_date)`
- **panel 视觉**：mini 卡 (`.tp-shell.content-card`)，含 header (`h3` + 笔数 + 刷新按钮) + body el-table

#### Scenario: panel 数据流（v13 嵌入模式）

- **WHEN** user 登录后打开 `/trade`
- **AND** `holdings.bootstrap()` 已完成（Pinia `orders.value` 已填今日数据）
- **THEN** `TodayOrdersPanel.todayOrders` MUST 渲染当日委托的 `order_flag !== 1` 子集
- **AND** MUST NOT 发任何 HTTP 请求（不走 `/api/orders`）
- **AND** ws `order_update` 来时 panel MUST 自动更新（Vue reactivity + `applyOrderPush`）

#### Scenario: panel 分页与 cache 共存

- **WHEN** 当前交易日有 50 笔委托 (≥20)
- **THEN** el-pagination MUST 显示，默认 page=1, pageSize=20 渲染前 20 笔
- **AND** ws 推送新增委托 → `orders.value` 数组增长 → pagination `:total` 同步增加
- **AND** ws 推送修改已渲染行的 `status` → 当前页对应 row MUST 实时更新状态标签

#### Scenario: panel 撤单仅作用于 activeDay 行

- **WHEN** panel 的 `todayOrders` computed 已过滤 `trd_date === activeDay`
- **THEN** panel 内 click-to-cancel MUST 只能触发 activeDay 撤单（broker 仅接受当日 trd_date）
- **AND** `cancelOrder(order_no, trd_date)` MUST 传 activeDay（`row.trd_date`）

### Requirement: 今日成交 panel（TodayTradesPanel 内嵌于 Trade.vue）

The system SHALL 提供 `client/src/components/trade/TodayTradesPanel.vue` 组件，作为
`Trade.vue` 右侧 sticky 列的下方面板，承载今日成交数据实时展示：

- **数据源**：`useHoldingsStore().trades`，Pinia 内存 + IDB write-through
- **范围过滤**（panel-local computed `todayTrades`）：
  - `trd_date === activeTrdDate`（仅当日）
  - `Number(trade_type) !== 1`（排除 cancel-fill，统计口径干净）
- **分页**：el-pagination 默认 20 行/页（与 TodayOrdersPanel 对称）
- **无撤单按钮**（trades 是终态历史，无可撤；与 history 语义一致）
- **panel 视觉**：同 `TodayOrdersPanel.vue` 结构

#### Scenario: panel 数据流（v13 嵌入模式）

- **WHEN** user 登录后打开 `/trade`
- **THEN** `TodayTradesPanel.todayTrades` MUST 渲染当日成交 (`trade_type !== 1`) 子集
- **AND** MUST NOT 发任何 HTTP 请求
- **AND** ws `trade_update` 来时 panel MUST 自动更新

#### Scenario: 成交金额本地计算

- **WHEN** panel 渲染 `price × volume` 列
- **THEN** MUST 用本地 `(Number(row.volume) || 0) * (Number(row.price) || 0)` 计算
- **AND** MUST NOT 引用 ws payload 的 `amount` 字段（与 holdings store 独立计算层一致）

### Requirement: Trade.vue 右侧双 panel 等分右列高度（v13）

The system SHALL 让 `Trade.vue` 右侧 `.trade-panels-col` 列内 `TodayOrdersPanel` 与 `TodayTradesPanel`
通过 `flex: 1 1 0; min-height: 0; overflow: hidden` 等分右列高度，避免 panel 内容短时下沿留白。

- `.trade-panels-col > * { flex: 1 1 0; min-height: 0; overflow: hidden }`
- 配合外层 `Trade.vue` `.trade-grid { flex: 1; min-height: 0 }` 形成完整 flex 链（详见 frontend capability "Trade.vue panel 上下填满"）

#### Scenario: 双 panel 等分右列

- **WHEN** viewport ≥ 1100px
- **THEN** 两个 panel 各占右列高度的 50%
- **AND** panel 内容短时下沿 MUST 不留白（el-empty 居中 + flex 撑满）
