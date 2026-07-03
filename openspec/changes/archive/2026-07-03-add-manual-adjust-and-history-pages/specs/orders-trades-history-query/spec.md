## ADDED Requirements

### Requirement: 历史委托视图（v12 新增）

The system SHALL 提供 `HistoryOrders.vue` 视图，按用户输入的 `start_date` / `end_date` / `stock_code` 实时查 `GET /api/orders` 并展示结果。**不走** Pinia 内存缓存（历史数据无"实时"概念）。

#### Scenario: 默认查询激活日

- **WHEN** user 进入 `/history/orders` 第 1 次
- **THEN** 默认 `start_date = active_day`，`end_date = active_day`
- **AND** `stock_code` 为空
- **AND** 立即发 `getOrders({ startDate: activeDay, endDate: activeDay })` 拉取

#### Scenario: 选择起止 + 股票过滤

- **WHEN** user 在 el-date-picker 选 `2026-06-01` 到 `2026-06-30`
- **AND** stockCode 输入框填 `600030.SH`
- **AND** 点"查询"按钮
- **THEN** 调 `getOrders({ startDate: '20260601', endDate: '20260630', stockCode: '600030.SH' })`
- **AND** 后端按区间 + stock_code 过滤

#### Scenario: 参数校验

- **WHEN** user 输入 `start_date > end_date`
- **THEN** 前端校验禁用"查询"按钮 + tooltip 提示

### Requirement: 历史成交通视图（同上）

The system SHALL 提供 `HistoryTrades.vue`，与历史委托视图对称，按 `start_date` / `end_date` / `stock_code` 查 `GET /api/trades`。

#### Scenario: 默认查询激活日

- 同 `HistoryOrders.vue`

#### Scenario: 选择起止 + 股票过滤

- 同 `HistoryOrders.vue`

### Requirement: History 页面不持有状态（契约）

The system SHALL 让 `HistoryOrders.vue` / `HistoryTrades.vue` 仅持有查询结果，不放入 `useHoldingsStore()` —— 历史数据非"业务实时"语义。

#### Scenario: HistoryOrders.vue 局部 state

- **WHEN** 实施本 change
- **THEN** `HistoryOrders.vue` 仅用 `ref([])` 局部 state 存查询结果
- **AND** 不调 `holdings.refreshOrders` 或任何 holdings.actions
- **AND** 每次"查询"按钮 = 新一次 HTTP 请求 + 覆盖局部 state

#### Scenario: 不持久化历史数据

- **WHEN** user 离开 `/history/orders`
- **THEN** 下次再回来 = 默认查询激活日 + 重新拉取
- **AND** 局部 state 不入 Pinia / 不入 IDB

### Requirement: 端点契约重申（v12）

`GET /api/orders` 与 `GET /api/trades` MUST 支持：
- `start_date=YYYYMMDD`（8 位数字字符串）—— 必填
- `end_date=YYYYMMDD`（8 位数字字符串）—— 必填
- `stock_code=...`（可选）
- 缺省时 = 激活日 trd_date（保持原契约）

排序：
- `/api/orders`：`ORDER BY order_time DESC`
- `/api/trades`：`ORDER BY trade_time DESC, trade_id DESC`（v8 二级 trade_id 兜底）

#### Scenario: 8 位数字校验

- **WHEN** 传 `start_date=2026-6-1`（非 8 位）
- **THEN** Pydantic 校验失败，返 422

#### Scenario: stock_code 可选

- **WHEN** 不传 `stock_code`
- **THEN** 返回该日期区间内的所有股票的委托

### Requirement: history 视图与 today 视图互斥加载

The system SHALL 确保 user 同时打开 `/today/orders` 与 `/history/orders` 时不会互相污染 —— 前者读 Pinia、后者读 HTTP。

#### Scenario: 两个 tab 同时打开

- **WHEN** user 开 2 个 tab：一个在 `/today/orders`、一个在 `/history/orders`
- **THEN** today tab 显示 Pinia 实时 orders；history tab 显示当前查询条件下的 HTTP 响应
- **AND** 两者独立，互不刷新
