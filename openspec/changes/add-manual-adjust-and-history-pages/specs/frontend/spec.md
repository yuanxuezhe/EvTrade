## MODIFIED Requirements

### Requirement: 业务数据生命周期 (v12 豁免：orders / trades 当日缓存走 IDB)

The system SHALL hold the 4 business data tables (资金 / 持仓 / 委托 / 成交) in Pinia stores as the in-memory source of truth. There is no client-side persistent storage (IDB / localStorage) for these tables **except 委托 / 成交 当日数据** —— 该例外见 `intraday-orders-trades-cache/spec.md`。

#### Scenario: 委托 / 成交 当日数据持久化例外

- **WHEN** user 打开 app / F5 刷新 / 关 tab 重开
- **THEN** `holdings.orders` 与 `holdings.trades` 走 IDB write-through，page reload 时按 `trd_date == active_day` 自动恢复
- **AND** `holdings.positions` 与 `holdings.cachedAsset` 仍然纯内存（bootstrap 时拉 + ws push 增量）

#### Scenario: positions / asset 不持久化

- **WHEN** user F5 刷新
- **THEN** `holdings.positions` 与 `holdings.cachedAsset` 重置为空
- **AND** 由 `bootstrap()` 重新从 `/api/positions` + `/api/asset` + 当前行情计算填充
- **AND** 与 v8 单源架构不冲突

### Requirement: 路由（v12 today / history 拆分）

The system SHALL 新增 4 个 today/history 路由到 router:

| 路径 | 视图 | 鉴权 |
|---|---|---|
| `/today/orders` | `TodayOrders.vue` | login |
| `/today/trades` | `TodayTrades.vue` | login |
| `/history/orders` | `HistoryOrders.vue` | login |
| `/history/trades` | `HistoryTrades.vue` | login |

#### Scenario: 旧路由 `/orders` 重定向

- **WHEN** user 导航到 `/orders`
- **THEN** router 重定向到 `/today/orders`（默认显示当日）

#### Scenario: 旧路由 `/trades` 重定向

- **WHEN** user 导航到 `/trades`
- **THEN** router 重定向到 `/today/trades`

### Requirement: ws push 同时写 Pinia + IDB（v12）

The system SHALL 在 ws push handler `applyOrderPush` / `applyTradePush` 内同时更新 Pinia ref 与 IDB store（仅 orders / trades）。

#### Scenario: ws push 即时双写

- **WHEN** ws 推 `order_update` 命中 `applyOrderPush`
- **THEN** `orders.value[idx]` 被替换 + IDB 中 `orders:by-date:active_day` store 同步增量
- **AND** IDB 写入失败不抛异常（try/catch + warn log）

#### Scenario: trd_cfm 双写 trades.value + IDB

- 同上，但触发方为 `applyTradePush`

#### Scenario: ws push 不写 IDB 的 2 个例外

- **WHEN** ws 推 `quote` 或 pos/asset（已删）触发 `applyQuote`
- **THEN** 仅写 Pinia（quote / positions 由前端实时计算），不写 IDB
- **AND** orders/trades 单独的双写路径与 quote 不混淆

## ADDED Requirements

### Requirement: holdings_idb.js 模块契约（v12）

`client/src/stores/holdings_idb.js` MUST 提供 6 个函数:
- `initIDB()` —— 打开 `EvTradeIDB`（version=1），含 `orders` / `trades` 两个 object store（keyPath=`_id`，复合 `{trd_date, order_no / trade_id}`）
- `saveOrdersForDate(trdDate, orders)` —— PUT `orders[trd_date]`
- `loadOrdersForDate(trdDate)` —— GET `orders[trd_date]` 或返 `[]`
- `saveTradesForDate(trdDate, trades)` —— 同 orders
- `loadTradesForDate(trdDate)` —— 同 orders
- `clearDate(trdDate)` —— 跨日时清掉上一交易日 IDB

#### Scenario: IDB 打开成功

- **WHEN** `initIDB()` 调
- **THEN** 返 IDB 实例引用；`orders` / `trades` object store 已建（首次含 upgrade callback）

#### Scenario: IDB 写异常不抛出

- **WHEN** `saveOrdersForDate` 内部 IDB 写失败（quota exceeded / 浏览器隐私模式）
- **THEN** 函数 catch 所有异常 + 打 console.warn
- **AND** 不影响 Pinia ref 的内存态

### Requirement: bootstrap 加载顺序（v12 详细化）

`holdings.bootstrap()` MUST 严格按以下顺序执行：
1. 读 `GET /api/system/active-day` 拿 `activeTrdDate`
2. 若 `activeTrdDate` 不为空 → 尝试 `loadOrdersForDate(activeTrdDate)` + `loadTradesForDate(activeTrdDate)`：
   - 命中则**先**用 IDB 数据初始化 Pinia ref（立刻显示）
   - 接着调 `ws.connect()` 等待 push 增量
   - **不**发 `/api/orders?trd_date=active_day` 二次拉取
3. 若 IDB 命中失败或 `activeTrdDate` 为空 → 走 fallback 路径：先发 `/api/orders?trd_date=active_day` + `/api/trades?trd_date=active_day` + 后续 ws connect
4. bootstrap 完成后 `loading=false, bootstrapped=true`

#### Scenario: IDB 命中（最常见）

- **WHEN** user F5 后 `activeTrdDate = "20260703"`
- **AND** IDB.orders["20260703"] 有 12 行
- **THEN** Pinia `orders.value = [12 rows]` 立刻渲染（< 50ms）
- **AND** 后续 ws `order_update` 来时按 `applyOrderPush` 增量合并

#### Scenario: 跨日（IDB.trd_date != active_day）

- **WHEN** IDB 中 orders 是昨天，但 activeTrdDate 是今天
- **THEN** `clearDate(yesterday)` 清 IDB
- **AND** 走 fallback 路径拉今天的当日数据

### Requirement: Trade.vue / Orders.vue 旧 view 删除（v12）

`client/src/views/Orders.vue` 与 `Trades.vue` MUST 被删除。`Trade.vue` 内嵌的"今日委托"表格 MUST 删除（改为链接跳 `/today/orders`）。

#### Scenario: Trade.vue 不含委托表

- **WHEN** 实施本 change
- **THEN** `Trade.vue` 不再含 `<el-table v-for=order>` 块
- **AND** 仅保留下单 + T0 决策区
- **AND** 顶部导航加 "今日委托 →" 链接到 `/today/orders`

### Requirement: 持仓表调平按钮（v12 新增）

`CachePositions.vue` 表格 MUST 在每行操作列加"调平"按钮 → 弹 dialog 输入 `delta_vol` / `delta_avl_vol` / `reason` → 调 `api.adjustPosition(stock_code, payload)`。

#### Scenario: 调平表单

- **WHEN** admin 点某行的「调平」
- **THEN** 弹 dialog 展示当前 `vol` / `avl_vol`（只读）+ 3 个输入字段
- **AND** `delta_vol` / `delta_avl_vol` 至少传一个，否则提交按钮 disabled
- **AND** `reason` max 255 chars（与后端 Pydantic validator 对齐）

#### Scenario: 调平成功后行替换

- **WHEN** 调 `api.adjustPosition` 成功（响应含 `position: PositionOut`）
- **THEN** 用 `resp.position` 替换该行 Pinia 数据（`positions.value.splice(idx, 1, newPos)`）
- **AND** 行 `synced_from` 渲染 `el-tag type=warning「manual」`
- **AND** ElMessage.success 显示 vol / avl_vol 新旧值

#### Scenario: 调平不影响其他业务数据

- **WHEN** 调平成功
- **THEN** `useHoldingsStore().cachedAsset` / `orders` / `trades` 不变
- **AND** `positions` 数组仅被调平的那一行被替换
