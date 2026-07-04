## MODIFIED Requirements

### Requirement: 路由表（v13：移除 /today/*, 统一指向 history）

调整 `REQ-FE-001` 路由表：

| 路径 | 视图 / 行为 | 鉴权 | 说明 |
|---|---|---|---|
| `/login` | Login.vue | public | 不变 |
| `/` | Dashboard.vue | login | 不变 |
| `/trade` | Trade.vue | trader | **v13 修订**：移除顶部"今日委托 →" / "今日成交 →" 外链；委托 / 成交数据**内嵌**到右侧两个 mini-panel（`TodayOrdersPanel` + `TodayTradesPanel`） |
| ~~`/today/orders`~~ | (删除) | — | **v13 移除**：由 `TodayOrdersPanel` 内嵌承担；`/orders` redirect 改成 `/history/orders` |
| ~~`/today/trades`~~ | (删除) | — | **v13 移除**：由 `TodayTradesPanel` 内嵌承担；`/trades` redirect 改成 `/history/trades` |
| `/history/orders` | `HistoryOrders.vue` | login | **v13 修订**：onMounted 留空（无默认查询）；加 4 个预设 chip |
| `/history/trades` | `HistoryTrades.vue` | login | **v13 修订**：同上 |
| `/orders` | → redirect `/history/orders` | login | **v13 修订**：redirect 目标从 `/today/orders` 改 `/history/orders` |
| `/trades` | → redirect `/history/trades` | login | **v13 修订**：redirect 目标从 `/today/trades` 改 `/history/trades` |
| `/today/orders` | → redirect `/history/orders` | login | **v13 新增**：老书签兼容 redirect |
| `/today/trades` | → redirect `/history/trades` | login | **v13 新增**：老书签兼容 redirect |
| 其余路由 | (保留) | (不变) | `/positions` `/t0-trade` `/t-strategy` `/algo-strategy` `/holdings` `/asset` `/users` `/profile` `/admin/cache/*` `/system-init` `/system-config` |

#### Scenario: /orders → /history/orders（v13 修订）

- **WHEN** user 导航到 `/orders`
- **THEN** router 重定向到 `/history/orders`（v13 之前是 `/today/orders`）

#### Scenario: /trades → /history/trades（v13 修订）

- **WHEN** user 导航到 `/trades`
- **THEN** router 重定向到 `/history/trades`（v13 之前是 `/today/trades`）

#### Scenario: 老书签 /today/* 兼容（v13 新增）

- **WHEN** 老用户书签跳 `/today/orders`
- **THEN** router 重定向到 `/history/orders`（不再 404）

#### Scenario: sidebar 标签改为历史（v13）

- **WHEN** user 登录后查看 sidebar
- **THEN** "委托查询" 标签改为 "历史委托"（路由仍 `/orders` → redirect `/history/orders`）
- **AND** "成交查询" 标签改为 "历史成交"（路由仍 `/trades` → redirect `/history/trades`）

## ADDED Requirements

### Requirement: Trade.vue 顶部不含 quicklinks

The system SHALL **删除** `Trade.vue` 模板顶部的 `<div class="trade-quicklinks">` 行（含"刷新"按钮等低价值入口）；用户改用 AppHeader 顶部的"刷新"按钮或 ws 推送实时更新。

#### Scenario: Trade.vue 无顶部 quicklinks

- **WHEN** user 导航到 `/trade`
- **THEN** `Trade.vue` 渲染时 MUST NOT 出现 `.trade-quicklinks` DOM 节点
- **AND** `Refresh` 图标 import 不在 `Trade.vue` script setup 中

### Requirement: Trade.vue 左列 flex 链整屏填充

The system SHALL 让 `Trade.vue` 左列 `.trade-form-col` 内的两个组件 (`OrderForm` + `QuotePanel`) 通过 `flex: 1 1 0; min-height: 0` 等分左列可用高度，避免在 OrderForm / QuotePanel 任一组件内容较短时出现底部空白。

#### Scenario: 双组件等分左列

- **WHEN** viewport ≥ 1100px 且左列渲染
- **THEN** `.trade-form-col > * { flex: 1 1 0; min-height: 0; overflow: hidden }` 生效
- **AND** OrderForm 与 QuotePanel 各占左列 50% 垂直空间
- **AND** 组件内容短时下沿不留白

### Requirement: 委托 / 成交 mini-panel 内嵌分页（20 行/页）

The system SHALL 让 `TodayOrdersPanel` 与 `TodayTradesPanel` 在表格下方加 `<el-pagination>`，
让单日委托 / 成交量大（>20 笔）的活跃日用户在 panel 内能翻页，**不**滚动整个 panel shell。

- `pageSize` 默认 `20`，`pageSizes: [10, 20, 50, 100]`
- `<el-table :data="pagedOrders|pagedTrades">` — `paged* = computed(() => today*.slice((page-1)*pageSize, page*pageSize))`
- pagination 不入 Pinia / 不入 IDB（panel-local state）
- pagination 切换 pageSize 或 page SHALL 触发 `<el-table>` 重新渲染（Vue reactivity）

#### Scenario: 20 笔成交时分页生效

- **WHEN** 当前交易日有 35 笔成交 (trd_date === activeDay) 且 trade_type !== 1
- **THEN** 默认 page=1, pageSize=20 显示前 20 笔
- **AND** 用户点 page 2 → 显示 21-35 笔
- **AND** 翻页后 el-table 滚动条归顶

#### Scenario: 0 笔时分页不显示

- **WHEN** 当前交易日 0 笔委托 / 成交
- **THEN** el-table 显示 el-empty
- **AND** el-pagination 隐藏 (`v-if="total > pageSize"`)

### Requirement: 撤单按钮只出现在今日数据源

The system SHALL 让撤单 UI 按钮仅在 `TodayOrdersPanel.vue` (内嵌在 Trade.vue) 出现；`HistoryOrders.vue` 与 `TodayTradesPanel.vue` MUST NOT 含撤单按钮（架构约束：撤单风控限定在当日 / 当前交易日）。

- 撤单 UI 控制范围：
  - **允许**：`TodayOrdersPanel.vue` 中 `canCancel(row)` 为 true 的行渲染"撤"按钮
  - **禁止**：`HistoryOrders.vue` 不含撤单列 / 撤单按钮 / `api.cancelOrder` 调用
  - **禁止**：`TodayTradesPanel.vue` 不含撤单按钮（trades 是终态历史）
- `TodayOrdersPanel.vue` 的 `canCancel(row)` MUST 满足：
  - `Number(row.order_flag) !== 1`（cancel-row 不再撤）
  - `row.status` 不在 broker 终态集 `{51, 52, 53, 54, 55, 56, 57}`
  - 数据范围 = `trd_date === activeTrdDate`（panel computed `todayOrders` 已强制）

#### Scenario: HistoryOrders.vue 无撤单列

- **WHEN** user 导航到 `/history/orders`
- **THEN** `HistoryOrders.vue` table 渲染 MUST NOT 出现"操作"列或任何撤单 UI
- **AND** `api.cancelOrder(...)` MUST NOT 在该 view 的 script setup 中被调用

#### Scenario: TodayTradesPanel.vue 无撤单按钮

- **WHEN** user 查看 `Trade.vue` 右下角 `TodayTradesPanel`
- **THEN** table MUST NOT 含"操作"列 / 撤单按钮（trades 是终态历史，无可撤数据）

#### Scenario: TodayOrdersPanel mini-panel 撤单仅作用于 activeDay 行

- **WHEN** `TodayOrdersPanel.todayOrders` computed 已过滤 `trd_date === activeDay` + `order_flag !== 1`
- **THEN** 该 panel 内 click-to-cancel 只能撤"今日委托"（broker 仅接受 `trd_date=activeDay` 撤单）

## REMOVED Requirements

### Requirement: Trade.vue 顶部"今日委托 →"/"今日成交 →" 外链按钮（v13 删除）

**Reason**：Trade.vue 顶部 quicklinks 行的低价值入口整体移除（含刷新按钮 + 委托/成交跳转链接）。委托/成交数据已内嵌到右侧两个 mini-panel，AppHeader 顶部已有"刷新"按钮，ws 推送也实时兜底；外链跳转成为冗余。

**Migration**：
- 删 `views/Trade.vue` 模板 `<div class="trade-quicklinks">` 块
- 删 `Refresh` 图标 import + `refreshing` ref + `refreshAll()` 函数
- 用户改用 AppHeader 顶部"刷新"按钮（已存在）或等待 ws 推送实时更新
