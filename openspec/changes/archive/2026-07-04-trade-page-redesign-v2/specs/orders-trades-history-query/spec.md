## MODIFIED Requirements

### Requirement: 历史委托视图（v12 + v13 预设 chip + 强制历史范围）

The system SHALL 提供 `HistoryOrders.vue` 视图，按用户输入的 `start_date` / `end_date` / `stock_code`
实时查 `GET /api/orders` 并展示结果。**不走** Pinia 内存缓存（历史数据无"实时"概念）。

**v13 修订**：
- onMounted MUST NOT 默认查询 activeDay（**留空**, 用户主动选）
- filter-bar MUST 加 4 个预设 chip 按钮（"昨日" / "最近三天" / "最近一周" / "最近一个月"）
- 任一 chip 点击 MUST 立即设置 `dateRange` 为对应历史范围 + 触发 `runQuery()`（不需先点"查询"）
- chip 高亮态 MUST 与 el-date-picker 双向联动（picker 范围 = 预设范围时，对应 chip 自动高亮）
- el-date-picker MUST 禁用 today / today 之后的日期（强制历史范围）

#### Scenario: 首次进入默认空状态

- **WHEN** user 第 1 次进入 `/history/orders`
- **THEN** `dateRange` MUST 为 null
- **AND** el-table MUST 渲染 el-empty（"请选择起止日期查询"）
- **AND** `api.getOrders` MUST NOT 在 onMounted 阶段被调用

#### Scenario: 选择起止 + 股票过滤

- **WHEN** user 在 el-date-picker 选 `2026-06-01` 到 `2026-06-30`
- **AND** stockCode 输入框填 `600030.SH`
- **AND** 点"查询"按钮
- **THEN** 调 `getOrders({ startDate: '20260601', endDate: '20260630', stockCode: '600030.SH' })`
- **AND** 后端按区间 + stock_code 过滤

#### Scenario: 参数校验

- **WHEN** user 输入 `start_date > end_date`
- **THEN** 前端校验禁用"查询"按钮 + tooltip 提示

#### Scenario: 点预设 chip 自动查询

- **WHEN** user 点"最近三天" chip
- **THEN** `dateRange` MUST 被设为 `[today-3, today-1]`（3 个日历日，**不含 today**）
- **AND** MUST 立即调 `runQuery()`，不等"查询"按钮
- **AND** chip MUST 切换到 active 高亮态

#### Scenario: chip 与 picker 双向联动

- **WHEN** user 手动改 picker 选 `[2026-06-01, 2026-06-30]`
- **THEN** 任意 chip MUST NOT 被高亮（chip 高亮态只响应"快捷预设范围"）
- **WHEN** user 手动选 picker 恰好等于"最近一周" chip 对应的 `[today-7, today-1]`
- **THEN** "最近一周" chip MUST 自动高亮

### Requirement: 历史成交通视图（v12 + v13 同上）

The system SHALL 提供 `HistoryTrades.vue`，与历史委托视图对称，按 `start_date` / `end_date` / `stock_code`
查 `GET /api/trades`。**v13 修订**行为与 `HistoryOrders.vue` 完全一致（onMounted 留空、4 个 chip、picker
禁 today+、chip ↔ picker 双向联动）。

#### Scenario: 默认空状态

- 同 `HistoryOrders.vue`（`dateRange = null`）

#### Scenario: 选择起止 + 股票过滤

- 同 `HistoryOrders.vue`

#### Scenario: 点预设 chip 自动查询

- 同 `HistoryOrders.vue`（成交版）

## ADDED Requirements

### Requirement: history 视图预设日期范围 chip（v13 新增）

The system SHALL 在 `HistoryOrders.vue` 与 `HistoryTrades.vue` 的 filter-bar 内提供 4 个 chip 按钮，
各自绑定固定历史区间，点击 MUST 立即触发查询：

| Chip label | dateRange (YYYYMMDD) | 计算 |
|---|---|---|
| 昨日 | `[today-1, today-1]` | `shiftDateStr(today, -1)` |
| 最近三天 | `[today-3, today-1]` | 含 today-3 / today-2 / today-1 共 3 个日历日，**不含 today** |
| 最近一周 | `[today-7, today-1]` | 含 today-7 ~ today-1 共 7 个日历日，**不含 today** |
| 最近一个月 | `[today-30, today-1]` | 含 today-30 ~ today-1 共 30 个日历日，**不含 today** |

`today` 取自浏览器本地时区 `new Date()`，与 `holdingsStore.activeTrdDate` 解耦
（这是 UI 层日期常量，非 broker 激活日；后端 start_date/end_date 仍按用户实际选取范围过滤）。

#### Scenario: 4 个 chip 渲染

- **WHEN** `/history/orders` 或 `/history/trades` 渲染
- **THEN** filter-bar MUST 出现 4 个 chip 按钮（label 按上表）
- **AND** chip MUST 可点击（hover 态 + active 高亮态 class）

#### Scenario: chip 与 picker 互不覆盖

- **WHEN** user 手动改 picker 改 dateRange
- **THEN** chip active 状态 MUST 仅当"picker 范围 == 预设范围" 时点亮
- **AND** chip active 类 MUST 在 picker 改动后即时更新（Vue reactivity + computed 双绑）

### Requirement: history 视图 dateRange 不含 today（v13 强制历史语义）

The system SHALL 让 `HistoryOrders.vue` 与 `HistoryTrades.vue` 的 el-date-picker 禁用 today
及未来日期，确保历史查询范围严格不包含 today（避免与 Trade.vue 内嵌 mini-panel 的今日数据语义混淆）。

- el-date-picker MUST 用 `:disabled-date="isAfterToday"` 控制可选范围
- `isAfterToday(date)` MUST 返 `true` 当 `date >= today` (`new Date()`)
- 历史语义约束："history view 的 dateRange MUST ≤ today-1"

#### Scenario: picker 禁用 today

- **WHEN** user 打开 history view 的 el-date-picker 日历面板
- **THEN** 今天及之后日期 MUST 显示为 disabled 样式（不可点击）
- **AND** 点击 disabled 日期 MUST NOT 改变 dateRange

### Requirement: history view onMounted 不默认查询（v13 留空）

The system SHALL 让 `HistoryOrders.vue` 与 `HistoryTrades.vue` 在 onMounted 阶段 MUST NOT 发起任何 `api.getOrders` / `api.getTrades` 请求，**留空**等用户主动选 chip 或 picker 范围。

- onMounted `dateRange = null`
- el-table 在 `hasQueried === false` 时 MUST 渲染 el-empty
- 用户首次有效查询来源：4 个 chip（首选） / 手动选 picker + 点"查询"

#### Scenario: onMounted 不发请求

- **WHEN** user 第 1 次进入 history view
- **THEN** MUST NOT 调 `api.getOrders` / `api.getTrades`
- **AND** MUST NOT 出现 v-loading 状态
- **AND** el-table MUST 渲染 el-empty

## REMOVED Requirements

### Requirement: history view onMounted 默认查询 activeDay（v13 删除）

**Reason**：v13 起 Trade.vue 内嵌 mini-panel 承担"今日"数据展示，history view 严格只服务历史数据；
若 onMounted 默认查 activeDay 会与 mini-panel 的当日数据重复展示，违反"今日数据 = Trade.vue 内嵌 + 缓存直读，历史数据 = 独立路由 + 后端区间"的分层语义。

**Migration**：
- `HistoryOrders.vue` / `HistoryTrades.vue` 的 `onMounted` 移除 `runQuery()` 调用
- `dateRange` 初值从 `[activeDay, activeDay]` 改 `null`
- 用户首次进入看到 el-empty + 4 个 chip 引导；点 chip 即查
