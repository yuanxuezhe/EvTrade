# frontend — Vue3 前端

> 📖 **DB schema**详见 [`data-model/spec.md`](../data-model/spec.md)（前端 store 与 DB schema 校对）
> 📖 **接口契约**详见 [`../../../docs/server-rest-api.md`](../../../docs/server-rest-api.md)（FastAPI 端点 + 出入参）

## Purpose

单页应用，12 个视图，WebSocket 实时更新，JWT 鉴权。
部署在 Windows dev 环境，监听 :50998。

## Requirements

### REQ-FE-100: 业务数据生命周期 (纯 Pinia 内存) — v12 豁免 orders / trades 当日走 IDB

The system SHALL hold the 4 business data tables (资金 / 持仓 / 委托 / 成交) in Pinia stores as the in-memory source of truth. **v12 豁免**：委托 / 成交 当日数据**走 IDB write-through**（详见 `intraday-orders-trades-cache/spec.md`），其他 2 类数据仍纯内存。

- 资金 → `useAssetStore().asset` （纯内存）
- 持仓 → `useHoldingsStore().positions` （纯内存，v8 单一源）
- 委托 → `useHoldingsStore().orders` （**v12 当日数据走 IDB**，详情见 REQ-FE-300 + `intraday-orders-trades-cache/spec.md`）
- 成交 → `useHoldingsStore().trades` （**v12 当日数据走 IDB**）

#### Scenario: 启动 (无持久化（除 v12 IDB 豁免）)

- **WHEN** user opens the app
- **THEN** Pinia stores start with empty initial values
- **AND** `holdingsStore.bootstrap()` (called after login) 立即尝试 IDB 命中 orders / trades 当日数据；命中即写 Pinia，跳过对应 RPC 拉取
- **AND** 未命中走 fallback：调 4 个 parallel API endpoints 拉 RPC

#### Scenario: API fetch → Pinia + IDB 异步双写（v12 委托/成交）

- **WHEN** `fetchAsset()` / `fetchPositions()` / `holdings.refreshAll()` 完成（asset / positions 仍纯内存，无 IDB）
- **OR** 当 `holdings.refreshAll()` 拉到 orders / trades 时，fire-and-forget `saveOrdersForDate(activeDay, ...)` + `saveTradesForDate(activeDay, ...)`
- **THEN** orders / trades 进入 Pinia 时也异步进入 IDB（不阻塞 caller）

#### Scenario: WS push → Pinia + IDB 增量（v12 委托/成交）

- **WHEN** ws push handler (`applyOrderPush` / `applyTradePush`) merges row into Pinia
- **THEN** IDB 同步增量（fire-and-forget）。仅 orders / trades；`applyQuote` 不动 IDB（quote 是实时短期态）
- **AND** IDB 写失败不抛异常（try/catch + console.warn；Pinia ref 不动）

#### Scenario: F5 刷新（v12 IDB 命中）

- **WHEN** user refreshes (F5) 且 IDB.orders["<activeDay>"] 存在
- **THEN** `holdings.orders` 200ms 内从 IDB 同步读回（不是空白）
- **AND** 后续 ws push 增量 merge 到 Pinia + IDB 双写
- **WHEN** IDB miss / 跨日
- **THEN** 清 IDB 旧 key + 走正常 RPC fallback

### REQ-FE-101: Admin 缓存查看器 (直读 Pinia CRUD)

The system SHALL provide an admin-only viewer with full CRUD (Create / Read / Update / Delete) **directly on the 4 Pinia business tables** (no IDB layer), available as 4 separate routes:

| Route | View | Pinia ref | Allowed Ops |
|---|---|---|---|
| `/admin/cache/asset`     | `CacheAsset.vue`     | `useAssetStore().asset`     | **Update only** (singleton 1 行) |
| `/admin/cache/positions` | `CachePositions.vue` | `useHoldingsStore().positions` | CRUD + Clear + **调平** (v12 新增 per-row API 调用) |
| `/admin/cache/orders`    | `CacheOrders.vue`    | `useHoldingsStore().orders`    | CRUD + Clear |
| `/admin/cache/trades`    | `CacheTrades.vue`    | `useHoldingsStore().trades`    | CRUD + Clear (composite key [trd_date, trade_id]) |

All 4 routes have `meta.requiresAdmin: true` — non-admin users are redirected to `/` by the global router guard at [client/src/router/index.js](../../client/src/router/index.js).

The shared component is [client/src/components/CacheTableView.vue](../../client/src/components/CacheTableView.vue) — receives `rowsRef` (响应式 ref) + `keyField` + `fields` + `allowAdd/Delete/Clear` flags. CRUD directly mutates the supplied ref, which is the same object the business pages read — no emit / re-fetch needed.

#### Scenario: 路由守卫

- **WHEN** non-admin user (role=trader / viewer) navigates to `/admin/cache/asset` (or any of the 4 cache routes)
- **THEN** router `beforeEach` guard redirects to `/` (silent — no error message)

#### Scenario: Sidebar 菜单

- **WHEN** admin user logs in
- **THEN** sidebar shows a "缓存查看" group with 4 sub-items (资金/持仓/委托/成交) — non-admin users do NOT see this group

#### Scenario: 资金表 (asset) 只允许改

- **WHEN** admin opens `/admin/cache/asset`
- **THEN** "新增" and "删" buttons are NOT shown (only "改" for the singleton row)
- **WHEN** admin edits the singleton row
- **THEN** `useAssetStore().asset` is mutated in place; the same object is read by `Asset.vue` (and via the watch — by `holdingsStore.cachedAsset`)

#### Scenario: 持仓 / 委托 / 成交表全 CRUD

- **WHEN** admin opens any of `/admin/cache/positions|orders|trades`
- **THEN** toolbar shows "清空 / 新增"; each row has "改 / 删" buttons
- **WHEN** admin edits, adds, or deletes a row
- **THEN** the array is mutated via `splice` / `unshift` so Vue's reactivity triggers downstream
- **WHEN** admin clicks "清空"
- **THEN** the array is emptied via `splice(0, length)`; the corresponding business page also shows empty data immediately

#### Scenario: 成交表 (trades) 复合主键

- **WHEN** admin edits or deletes a trade row
- **THEN** key is the array `[trd_date, trade_id]` (composite key); both fields are disabled in the edit dialog

#### Scenario: 改动只影响本地 (同源 ref)

- **WHEN** admin performs any CRUD in the cache viewer
- **THEN** changes mutate the Pinia ref directly; NO server API call is made
- **AND** business pages (e.g. `Holdings.vue`, `Orders.vue`) which read the **same ref** see the new data immediately via Vue's reactive propagation — no manual refresh, no event emit, no store action

#### Scenario: 列名带英文 key 后缀

- **WHEN** admin views any cache table (header or edit dialog form-item)
- **THEN** each column label renders as `"中文 (english_key)"` e.g. `现金 (cash)`, `总资产 (total_asset)` — so admin can directly map displayed column to the actual Pinia field key without consulting the schema separately

#### Scenario: 持仓表调平按钮（v12 新增）

- **WHEN** admin 打开 `/admin/cache/positions` 并点某行的「调平」按钮
- **THEN** 弹 dialog，输入 `delta_vol` / `delta_avl_vol` / `reason`（至少一个 delta 字段）
- **AND** 提交后调 `api.adjustPosition(stock_code, {deltaVol, deltaAvlVol, reason})` → `PUT /api/positions/{stock_code}/adjust`
- **AND** 成功响应后用 `resp.position` 替换该行 Pinia 数据（直接 splice）
- **AND** 行 `synced_from` 变为 `manual` 标签，下次 `do_reconcile` 会重置为 `rpc_full`



### REQ-FE-001: 路由（v13：移除 /today/*, 统一指向 history）

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
| `/positions` | → redirect `/t0-trade` | login | 旧 `/to-management` 路径合并 |
| `/t0-trade` | T0Trade.vue（快速做T） | login | |
| `/t-strategy` | TStrategy.vue（策略做T） | login | |
| `/algo-strategy` | AlgoStrategy.vue | login | |
| `/holdings` | Holdings.vue | login | |
| `/asset` | Asset.vue | login | |
| `/users` | Users.vue | admin | |
| `/profile` | Profile.vue | login | |
| `/admin/cache/{asset,positions,orders,trades}` | `Cache*.vue` | admin | CachePositions.vue v12 加"调平"按钮（API: `PUT /api/positions/{stock_code}/adjust`） |
| `/system-init` / `/system-config` | SystemInit.vue / SystemConfig.vue | admin | |

### REQ-FE-002: API 客户端

- 入口 `client/src/api/index.js` 导出 axios 实例
- 拦截器：401 → 清 token + 跳 `/login`
- 拦截器：RPC 响应统一处理 — `code≠0` 时弹 ElMessage.error + reject
- 拦截器自动把 `{code, msg, list}` 展平为 `list` 数组

### REQ-FE-003: Pinia stores

| Store | 职责 | 数据源 |
|---|---|---|
| `auth` | JWT、用户信息、角色 | `/api/auth/*` |
| `ui` | 通用 UI 状态（侧栏折叠等） | localStorage |
| `order` | 委托操作 actions（不持有数据） | `/api/orders/place` + `holdings` |
| `position` | 持仓 | `/api/positions` |
| `asset` | 资金 | `/api/asset` |
| `holdings` | **唯一缓存源**（资金/委托/成交/持仓/activeTrdDate） | 批量 `/api/...` + WS `order_update`/`trade_update` |
| `quote` | 行情订阅列表 | WS `quote_update` |
| `ws` | WebSocket 连接管理 | — |

### REQ-FE-009: 委托/成交单一缓存源（v8）

- **唯一权威**：`holdings` store 持有 `orders / trades / positions / asset / activeTrdDate`
- **`order.js` 重写为纯 actions**（不持有 orders/trades）：
  - `placeOrder` → RPC 调用 → 拦截器解包 → `_upsertToHoldings(list[0])` 立即 unshift 到 holdings.orders
  - `cancelOrder` → 委托 `holdings.applyOrderPush(...)` 写一条 status=53 占位（broker ord_cfm 真正到达时再覆盖）
  - **不暴露** `orders / trades` getter，强制 view 显式 `useHoldingsStore().orders`
- **`ws.js` 推送单点入口**：`_onOrderCfm` / `_onTradeCfm` **只调** `holdings.applyOrderPush/applyTradePush`
  - 删 `useOrderStore` 引用
  - 匹配键 `order_no`，兜底 `row.remark`
  - WS 不再双写 orderStore + holdings
- **视图层约束**：
  - `Trade.vue`：删 `onMounted(fetchOrders)` 与 `setInterval(fetchOrders, 5000)` 轮询；改用 `holdings.refreshAll` 手动刷新按钮（兜底）
  - `T0Trade.vue`：`submitOrder` 改走 `orderStore.placeOrder`（自动 upsert holdings）；旧 `res.code === 0` 检查改为 `res`（拦截器解包后是 OrderOut 对象）
- 详见归档 `archive/2026-06-21-order-push-trd-date-authority/spec-deltas/frontend.md`

#### REQ-FE-009.3: 禁止直接访问 `orderStore` state（v8 视图约束）

- **MUST NOT** 视图组件直接访问 `orderStore.{orders, trades, positions, asset, activeTrdDate}`
  - v8 后 `order.js` 显式 **不暴露** 这 5 个 getter（`order.js` L74-82 注释："避免独立缓存误解"）
  - 视图层访问 → undefined → Vue render 崩 (`X is not iterable` / `Cannot read properties of undefined`)
- **MUST** 改用 `useHoldingsStore()`（权威源）：
  - `holdingsStore.orders` / `holdingsStore.trades` / `holdingsStore.positions` / `holdingsStore.cachedAsset` / `holdingsStore.liveTotalAsset`
- **唯一允许**：调用 `orderStore` 的 **actions**（`placeOrder` / `cancelOrder` / `createOrder`）
- 详见归档 `archive/2026-06-22-fix-v8-single-source-violations/spec-deltas/frontend.md`

#### REQ-FE-009.4: 禁止调用 v8 已删除的 fetcher
#### REQ-FE-009.5: 撤单审计行（cancel-row）短路（v9，v11 broker 码）

- `holdings.applyOrderPush(row, action)`: 见 `row.order_flag === 1` 时**直接 merge + return**，**不**走 `_recomputeStatus`
  - 原因：cancel-row `volume=0, traded_volume=0`，`_recomputeStatus` 推算结果会是 `50`（broker 已报），污染显示
  - cancel-row 的 `status` MUST 由 DELETE 端点全权管理（v11 broker 码：54 已撤 / 57 废单），前端只 merge 不重算
  - 日志用「撤单审计」前缀区分正常推送

#### Scenario: cancel-row status 短路（v11 修订）

- **WHEN** applyOrderPush 收到 order_flag=1 的 cancel-row，row.status='54'（broker 已撤）
- **THEN** 直接 merge 到 orders.value，不调 inferOrderStatus
- **AND** 视图层 Trade.vue / Orders.vue 显示「类型=撤单」标签（cancel-row 守卫）

- `holdings.applyTradePush(row)`: 透传 `trade_type` 字段（0=normal 1=cancel-fill）
  - `trade_type === 1` 时记「撤单审计」日志（区分正常成交通知）

#### REQ-FE-009.6: 撤单审计视图契约（v9）

- Trade.vue「今日委托」表格：
  - 加「类型」列：`order_flag === 1` 渲染 `el-tag type=warning「撤单」`；其他显示「委托」
  - 过滤选项新增 `allWithAudit`（显示 cancel-row）；默认 `all/pending/filled` **隐藏** cancel-row
  - `canCancel(row)` 加 `row.order_flag === 1` 守卫（cancel-row 不可再撤）
  - `pendingCount` 排除 cancel-row（cancel-row 不算待成交）
- Orders.vue「委托查询」表格：
  - 加「委托类型」列（同 Trade.vue 渲染规则；区别于「类型」列是 `price_type` 限价/市价）
  - `countByStatus` 排除 `order_flag === 1`（cancel-row volume=0 不计入正常委托统计口径）
  - `getFillRate(row)` 加 `order_flag === 1` 守卫直接返 100（volume=0 → 0/0=NaN 修复）
- Trades.vue「成交查询」表格：
  - 加「类型」列：`trade_type === 1` 渲染 `el-tag type=warning「撤单」`；其他显示「成交」
  - `buyCount/sellCount/buyAmount/sellAmount` 排除 `trade_type === 1`（cancel-fill 不计入买/卖统计）

- **`orderStore.fetchOrders()` / `orderStore.fetchOrders(stockCode)`** 已删除 — v8 委托由 ws `order_update` push 兜底
- **`orderStore.fetchTrades()` / `orderStore.fetchTrades(stockCode)`** 已删除 — v8 成交由 ws `trade_update` push 兜底
- **MUST**: 委托/成交加载走 `holdingsStore.bootstrap()` (App 启动) 或 `holdingsStore.refreshAll()` (手动刷新)
- 详见归档 `archive/2026-06-22-fix-v8-single-source-violations-r2/spec-deltas/frontend.md`

#### REQ-FE-009.7: holdings store 拆分（phase-2 facade）

- **位置**：
  - `client/src/stores/holdings.js` — Pinia store facade（单 store,装配 4 helper）
  - `client/src/stores/holdings_log.js` — `createLogger(loadHistory)` 操作流水（MAX_HISTORY=200）
  - `client/src/stores/holdings_helpers.js` — `parseAsset` / `recomputeStatus` / `nowHMS` / `todayYYYYMMDD` 纯函数
  - `client/src/stores/holdings_market.js` — `createMarketComputeds(positions, cachedAsset, getQuoteStore)` 实时市值/盈亏 computed 工厂
  - `client/src/stores/holdings_push.js` — `createPushHandlers({...deps})` 5 个 ws 推送入口（v8 trd_date 守门 + v9 cancel-row/trade_type 短路）
- **R3 reactivity 守门**：**必须保持单 Pinia store facade**（21 view 都 `useHoldingsStore()`），不允许拆成 5 个独立 store 后让 view 各自调。helper 全部是**纯工厂函数**，state 仍由 facade 持有
- **facade 暴露 surface（21 view 引用安全网）**：
  - state: `positions / orders / trades / cachedAsset / loadHistory / activeTrdDate / activeDayStatus / loading / bootstrapped / lastUpdated / refCounts`
  - computed: `liveMarketValue / liveTotalAsset / positionCodes`
  - actions: `bootstrap / refreshAll / refreshPositions / refreshAsset / log / clearHistory / _startWatchers / _stopWatchers`
  - getters: `getLivePrice / getMarketValue / getProfit / getReturnRate`
  - ws push: `applyPositionPush / applyAssetPush / applyOrderPush / applyTradePush / applyQuote`

#### REQ-FE-009.8: 委托/成交 trd_date 区间查询与展示（2026-06-30）

- **位置**：
  - `client/src/utils/trdDateFilter.js` — `filterByTrdDate(items, range)` 三模式纯函数（exact / [start,end] / 无过滤）
  - `client/src/utils/date.js` — `shiftDateStr(yyyymmdd, deltaDays)` 跨月/跨年/闰年工具
  - `client/src/stores/holdings_bootstrap.js` — `BOOTSTRAP_WINDOW_DAYS = 30`；bootstrap 拉 `[activeDate-29, activeDate]` 区间全量
  - `client/src/api/index.js` — `getOrders({ startDate, endDate })` / `getTrades({ startDate, endDate })` opts 对象入参
  - `client/src/views/Orders.vue` — `<el-tabs>`「仅当日 / 全部」 + trd_date 列 + `filteredOrders` computed
  - `client/src/views/Trades.vue` — trd_date 列 + `default-sort: { prop: 'trade_time', order: 'descending' }`（v9 已删 `order_id` 列不再显示）

- **filterByTrdDate 契约**：
  - `range = { exact?: string, start?: string, end?: string }`
  - `exact` 与 `start/end` 互斥，同时给 `exact` 优先
  - 缺省 `range = {}` 时返回 `items.slice()`（不污染调用方引用）
  - YYYYMMDD 字符串比较天然字典序 = 时间序，无需 parse

- **bootstrap 拉取窗口**：
  - `endDate = activeTrdDate.value`（已由 `_resolveActiveDay()` 解析）
  - `startDate = shiftDateStr(endDate, -30)`
  - holdings store 仍只持单 ref，存 30 天窗口全量
  - WS 推送守门不受影响（用 `trd_date === activeTrdDate` 单值比较，与拉取窗口解耦）

- **向后兼容**：
  - `getOrders()` / `getTrades()` 无 opts 时行为不变（激活日单日）
  - `OrderOut.trd_date` / `TradeOut.trd_date` 字段已在（v6/v7 已加）

- 详见归档 `archive/2026-06-30-order-trade-query-by-trd-date/spec-deltas/frontend.md`
- **依赖注入模式**：helper 工厂通过参数接收 state ref + store getter（如 `getQuoteStore: () => useQuoteStore()`），避免循环依赖
- 详见归档 `archive/2026-06-24-phase-2-architecture-split/spec-deltas/frontend.md`

### REQ-FE-009.9: 前端独立计算委托 / 成交缓存（v11 broker 码）

ws 推送的 trd_cfm payload 仅含当前笔 trade 字段；前端 holdings store 缓存层 MUST 独立维护以下计算字段——**不读 ws 推送 payload 的累积 / cancelled_volume / status 字段**：

#### Scenario: 增量累计 status 输出 broker 码

- **WHEN** order.volume=100, traded_volume=30, cancelled_volume=0, status='50'（broker 已报）
- **AND** applyTradePush 收到 volume=30 的新成交
- **THEN** recomputeOrderFromTrade 累计后 order.status='55'（broker 部成）

#### Scenario: cancel-row 反向抹平后 status 输出 broker 码

- **WHEN** order.volume=100, traded_volume=30, cancelled_volume=0, status='55'（broker 部成）
- **AND** applyOrderPush 收到 cancel-row (order_flag=1) 反向抹平 cancelled_volume=100
- **THEN** 反向抹平后 order.status='53'（broker 部成部撤），不是本地推断码 56

- **`trades.amount`**：本地 `price × volume` 计算，不引用 ws payload 的 amount 字段
- **`orders.traded_volume`**：各 trd_cfm 单笔 `volume` 在对应 `order_no` 上增量累加
- **`orders.traded_amount`**：各 trd_cfm 单笔 `price × volume` 在对应 `order_no` 上增量累加
- **`orders.avg_price`**：`traded_amount / traded_volume`（仅防 `traded_volume == 0` 除零）
- **`orders.status`**：调 `inferOrderStatus(order, null)` 本地推断（不传 brokerStatus），与后端 `_infer_order_status` 镜像
- **`orders.cancelled_volume`**：
  - bootstrap / refresh 拉取时：接受 row 字段作为初始值
  - 运行时：cancel-row ws 推送（`order_flag === 1`）按 `user_def = 'CANCEL:{orig_order_no}'` 反向定位原委托，把 `orig.cancelled_volume = orig.volume` 一次性抹平

ws 推送的 `order_update` payload SHALL 仅用于 PK + 元数据覆盖（`order_id / user_def / order_time / stock_code / order_type / price_type / price / volume / status_msg`），MUST NOT 覆盖 `traded_volume / traded_amount / avg_price / cancelled_volume / status` 等本地维护字段。

bootstrap 与 refresh 路径（`/api/orders` 与 `/api/trades` 拉取响应）SHALL 接受 row 累计字段作为初始值，再重算 `avg_price / status / cancelled_volume`。

Vue ref 响应式 SHALL 支持实时 UI 渲染：所有改动通过 `value[idx] = newObj` 触发，holdings store 的 ref 数组自动触发 `<el-table>` 等 watcher。

### REQ-FE-009.9.1: 前端 helper 工具函数（v11 输出码全集 broker 码）

The system SHALL 在 `client/src/utils/orderCalc.js` MUST 提供的 helper 函数输出 broker 码:

- `normalizeTrade(trade)`：返回 `{...trade, amount: price × volume}`
- `recomputeOrderFromTrade(order, trade)`：返回基于单笔 trade 增量累计的新 order 对象（含 status 推断, 输出 broker 码）
- `metaMerge(row, ref)`：返回仅覆盖 PK + 元数据、保留 ref 计算字段的合并结果
- `flattenCancelledByRow(row, orders)`：cancel-row 触发的反向抹平逻辑

#### Scenario: recomputeOrderFromTrade 输出 broker 码

- **WHEN** order.volume=100, traded_volume=0, trade.volume=30
- **THEN** 返回新 order 的 status='55'（broker 部成），不是本地推断码 50

#### Scenario: flattenCancelledByRow 触发 broker 53

- **WHEN** order.volume=100, traded_volume=30, cancelled_volume=0, status='55'（broker 部成）
- **AND** cancel-row 反向抹平 cancelled_volume=100
- **THEN** 返回新 order 的 status='53'（broker 部成部撤），不是本地推断码 56

helper 函数 MUST 与后端 `handle_trd_cfm / api/orders/place.py / api/orders/cancel.py / handle_ord_cfm` 等写入路径字段语义逐字对齐，避免前后端算法漂移。

### REQ-FE-006: 委托 status 本地推断（v11 broker 字典对齐）

`client/src/utils/format.js` 导出 `inferOrderStatus(order, brokerStatus?)` 函数 MUST 与 `server/services/order_status.py:_infer_order_status` **逐行一致**，输出码全集 {50, 53, 54, 55, 56}（全是 broker xtconstant 码，无本地扩展）。

#### Scenario: 推断输出码全集是 broker 码

- **WHEN** order.volume=100, traded_volume=50, cancelled_volume=0, status='50'
- **THEN** inferOrderStatus 输出 '55'（broker 部成），不是本地推断码 50

#### Scenario: 终态保持（含 broker 52）

- **WHEN** order.status='52'（broker 部成待撤）
- **THEN** inferOrderStatus 保持 '52'

#### Scenario: 视图层按 broker 字典分组

- **WHEN** Trade.vue 显示今日委托表
- **THEN** `_PENDING_NUMERIC` 包含 {48, 49, 50}（broker 未报/待报/已报）
- **AND** `_FILLED_NUMERIC` 包含 {55, 56, 54}（broker 部成/已成/已撤）
- **AND** `_PARTIAL_CANCEL_NUMERIC` 包含 {53}（broker 部成部撤）

- **位置**：`client/src/utils/format.js` 导出 `inferOrderStatus(order, brokerStatus?)` 函数
- **契约**：与 `server/services/push_handlers.py:_infer_order_status` **逐行一致**（同规则、同终态集合、同输入输出）
- **v11 broker 字典对齐**：输出码全集 {50, 53, 54, 55, 56} 改 broker 码
- **v8 修订**（历史保留）：入参 `order` 增加 `cancelled_volume` 字段；推断规则以 `cancelled_volume` 主轴（详见 `push/spec.md` REQ-PUSH-005 v8 修订部分）
- **调用点**（v8 修订）：
  - `holdings.js:bootstrap` 拉取 `/api/orders` 后批量重算
  - `holdings.js:refresh` 拉取 `/api/orders` 后批量重算
  - `holdings.js:applyOrderPush` 收到 `order_update` 时重算
  - 统一通过 `holdings.js:_recomputeStatus(row)` helper 实现（不传 brokerStatus，按 cancelled_volume + traded_volume / volume 推断）
- **视图层契约**：
  - 状态码分组集合（`_PENDING_NUMERIC` / `_FILLED_NUMERIC` / `countByStatus`）必须用 **broker xtconstant 字典**：48/49/50/51/52/53/54/55/56/255（v11 起）
  - 不要再用 broker 原始码（55=部成/56=已成）的旧逻辑
  - **不信任后端 / broker 推的 status 字段**：所有显示路径必须经 `inferOrderStatus` 重算（防御性）
- **Trade.vue 列展示**：
  - 数量 / 价格 / 已成 / **已撤** / 状态 / 操作
  - "已撤"列直接展示 `row.cancelled_volume || 0`（与状态列联动：已撤时显示撤单数）

### REQ-FE-007: 撤单 API 用 order_no + trd_date

- `api.cancelOrder(orderNo, trdDate)` 调 `DELETE /api/orders/${orderNo}?trd_date=${trdDate}`
- `orderStore.cancelOrder(orderNo, trdDate)` 不再接受 `orderId`
- `trdDate` 默认值取自 `holdingsStore.cachedAsset.trd_date` 或当前激活日（active SysStatus）
- **BREAKING**：旧的 `cancelOrder(orderId)` 调用方式全部改掉

### REQ-FE-008: 委托表格显示 order_no

- Trade.vue「今日委托」表格 + Orders.vue「委托查询」表格：增加 `order_no` 列
- 撤单按钮：`@click="handleCancel(row.order_no, row.trd_date)"`
- 显示：`<span class="text-mono text-secondary">{{ row.order_no }}</span>`

### REQ-FE-004: WebSocket

- 业务频道（`order_update` 等）连 `ws://<host>:8000/ws/<channel>`
- 行情频道（`quote_update`）连 `ws://<host>:8765`（hqserver）

### REQ-FE-005: UI 偏好（来自 user memory）

- 固定条默认折叠为单行
- 折叠态不显示标题
- 背景实心不透明
- 不重复按钮
- 流水按标签 `check-tag` 筛选


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

### Requirement: OperationLog 折叠状态对视图可见（oPlogExpanded 共享）

The system SHALL 通过 `uiStore` 暴露底部固定 OperationLog 栏的折叠状态，供任意视图响应式读取，
使得依赖 viewport-calc 的布局（典型场景为 sticky 元素的 max-height）能跟随 OperationLog
实际高度变化，避免内容被底部操作记录栏遮挡。

`uiStore` MUST 暴露以下 surface：
- `oplogExpanded: boolean` —— `true` 表示展开（OperationLog 高度 320px），`false` 表示折叠（44px）
- `setOplogExpanded(value: boolean): void` —— 直接设置状态
- `toggleOplog(): void` —— 切换状态

App.vue 的 `<OperationLog>` MUST 用 `v-model:expanded="uiStore.oplogExpanded"` 双向绑定，
保证 OperationLog 内部 toggle 与 uiStore 状态同步；任一端的状态变化 SHALL 通过响应式传播到
所有读取 `uiStore.oplogExpanded` 的视图。

#### Scenario: 默认状态可见

- **WHEN** user 登录后尚未交互
- **THEN** `uiStore.oplogExpanded === false`（默认折叠）
- **AND** OperationLog 高度 = 44px

#### Scenario: 用户展开 OperationLog 后 uiStore 同步

- **WHEN** user 点 OperationLog 标题栏 / 收缩按钮
- **THEN** `uiStore.oplogExpanded` 切换为 `true`
- **AND** OperationLog 高度 = 320px
- **AND** 任一视图（如 Trade.vue）通过 `computed` 读取 `uiStore.oplogExpanded` 的 CSS var MUST
  在同一帧重新求值（Vue reactivity）

#### Scenario: 外部调用 setOplogExpanded 也同步到组件

- **WHEN** 任意代码（含 devtools / 自动化测试）调 `uiStore.setOplogExpanded(true)`
- **THEN** OperationLog 的 `update:expanded` emit 触发 → props 同步 → 折叠状态切到展开

### Requirement: Trade.vue panel 上下填满 + 不被 OperationLog 遮挡

The system SHALL ensure `Trade.vue` 右侧 `.trade-panels-col`（含 TodayOrdersPanel +
TodayTradesPanel 两个 mini-panel）通过 flex 链填满 `.app-content` 的可用垂直空间，
避免在 panel 内容较短时下方出现空白。同时 sticky 行为下的 panel 顶部 SHALL 永远在
OperationLog 上沿之上，不被底部操作记录栏遮挡。

实现 MUST 满足以下行为契约：

- `.trade-view` MUST 设 `height: 100%`（填父容器 `.app-content` 的 content area）
- `.trade-grid` MUST 设 `flex: 1; min-height: 0`（占据 `.trade-view` 中除 `.trade-quicklinks` 外的剩余垂直空间）
- `.trade-panels-col > *` 每个 panel MUST 设 `flex: 1 1 0; min-height: 0; overflow: hidden`
  （强制等分右列高度；任一 panel 都不会因内容短而塌陷留白）
- `.trade-panels-col` MUST 注入 `--oplog-h` CSS var（值取自 `uiStore.oplogExpanded`：
  折叠 44px / 展开 320px）
- 右侧 panel 列的 `max-height` MUST 计算为 `calc(100vh - <AppHeader+padding-y>px - var(--oplog-h, 44px))`，
  保证 sticky panel 底部在 OperationLog 上沿之下
- panel 内部 `el-table` 的 max-height MUST 用 `'100%'`（跟随父 `.tp-body { flex: 1 }`），
  禁止用 `calc(100vh - N)`（避免与外层 sticky max-height 双重截断产生空白）

窄屏（`<1100px` viewport 宽度）下 MUST 切换为单列堆叠：`.trade-grid` 改单列，
`.trade-panels-col` 取消 sticky 与 max-height，让 panel 跟随内容自然高度，保证移动端可读性。

#### Scenario: 默认状态（OperationLog 折叠、宽屏）

- **WHEN** user 登录后导航到 `/trade` 且 OperationLog 折叠（44px）且 viewport ≥ 1100px
- **THEN** `.trade-panels-col` max-height = `calc(100vh - 80px - 44px) = 100vh - 124px`
- **AND** panel 列底部与 OperationLog 顶部对齐（无重叠）
- **AND** 两个 panel 等分右列高度（各 `flex: 1 1 0`）
- **AND** panel 内容（el-table）`max-height: 100%` 填满 panel 内部 `.tp-body`

#### Scenario: OperationLog 展开时 panel 自动收紧

- **WHEN** user 点 OperationLog 标题栏展开（高度变 320px）
- **THEN** `uiStore.oplogExpanded === true`
- **AND** `.trade-view { --oplog-h: 320px }` 通过 `:style` 重新求值
- **AND** `.trade-panels-col` max-height 自动收紧到 `calc(100vh - 80 - 320) = 100vh - 400px`
- **AND** panel 列底部重新对齐到 OperationLog 顶部

#### Scenario: 窄屏 (<1100px) 单列堆叠

- **WHEN** viewport 宽度 < 1100px
- **THEN** `@media (max-width: 1100px)` 生效
- **AND** `.trade-grid { grid-template-columns: 1fr }`（单列）
- **AND** `.trade-panels-col` 取消 `position: sticky` 和 `max-height`
- **AND** panel 跟随内容自然高度（不强制 `flex: 1`）

#### Scenario: 内容短时 panel 仍填满右列（不留底部空白）

- **WHEN** user 当前交易日有 0 笔委托 + 0 笔成交
- **THEN** 两个 panel shell 显示 el-empty（空状态）
- **AND** panel `.tp-shell` 高度仍 = 右列高度的 ½（由 `flex: 1 1 0` 决定）
- **AND** el-empty 居中显示在 panel `.tp-body` 中
- **AND** panel 总高度 = `.trade-panels-col` 高度 - `var(--space-3)` gap

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

### Scenarios

#### S-FE-001: 未登录访问 `/orders`

When 浏览器请求 `/orders`
Then router.beforeEach 检测到无 token → 重定向 `/login?redirect=/orders`
And 登录成功后跳回 `/orders`

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

### S-FE-002: viewer 访问 `/trade`

When viewer 角色访问 `/trade`  
Then router 检测到 `requiresTrader` 不满足 → 重定向 `/`

### S-FE-003: 行情实时推送

When QMT 推一条 `600030.SH|...|12.34|...` 到 RabbitMQ  
Then hqserver WS 推 `{"channel":"quote_update","data":{...}}`  
And 前端 `quote` store 更新对应 stock_code 的 last_price  
And Asset/Holdings 等视图若订阅了该股则自动刷新

### REQ-FE-010: 委托价格输入支持小数（v8）

- **位置**：`client/src/components/OrderForm.vue`
- **契约**：
  - 限价单（`price_type === PriceType.FIX_PRICE`）委托价格输入支持 2 位小数（A 股最小变动单位 0.01 元）

### REQ-FE-011: 前端 5 张字典按 broker 义重映射（v11）

`STATUS_LABEL` / `STATUS_TYPE` / `STATUS_TONE` / `STATUS_ICON_NAME` / `STATUS_PULSE` / `STATUS_OPTIONS` MUST 按 broker xtconstant 字典义重映射。

#### Scenario: STATUS_LABEL 按 broker 义（v11 新增）

- **WHEN** 视图层渲染订单状态
- **THEN** `STATUS_LABEL['54']` = '已撤'（broker CANCELED）
- **AND** `STATUS_LABEL['57']` = '废单'（broker JUNK）
- **AND** `STATUS_LABEL['53']` = '部成部撤'（broker PART_CANCEL）
- **AND** `STATUS_LABEL['55']` = '部成'（broker PART_SUCC）
- **AND** `STATUS_LABEL['56']` = '已成'（broker SUCCEEDED）

#### Scenario: STATUS_OPTIONS 按 broker 字典顺序（v11 新增）

- **WHEN** Trade.vue / Orders.vue 渲染状态过滤下拉
- **THEN** STATUS_OPTIONS 按 broker 字典顺序：48→待报 / 49→待报 / 50→已报 / 51→已报待撤 / 52→部成待撤 / 53→部成部撤 / 54→已撤 / 55→部成 / 56→已成 / 57→废单 / 255→未知

#### Scenario: STATUS_PULSE 中间态脉冲（v11 新增）

- **WHEN** 视图层渲染订单状态
- **THEN** 48/49/50/51/52/55 等中间态 MUST 有脉冲动画（true）
- **AND** 53/54/56/57/255 等终态 MUST 无脉冲动画（false）

### Requirement: OrderForm 三段全宽垂直堆叠（价格类型 / 委托价格 / 委托数量）

The system SHALL 让 `client/src/components/OrderForm.vue` 中
`价格类型` / `委托价格` / `委托数量` 三段各自渲染为独立的 `<el-form-item>`,
每段占满 `<el-form>` 100% 宽度（不再任何 grid 容器共享横向空间）,
确保 `el-segmented` 4 段 (限价 / 最新价 / 挂单价 / 市价) label 在 Trade.vue 左列窄宽度下全部完整可见。

- 字段顺序 MUST 保持: `股票代码` → `价格类型` → `委托价格` → `委托数量`
- 每段 MUST NOT 用 `<div class="price-row">` 等 grid 容器包裹
- `.price-row` / `.price-type-col { min-width: 180px }` / `.price-col` CSS MUST 全部删除

#### Scenario: 价格类型 2×2 radio 网格渲染（r2: 替换 el-segmented）

- **WHEN** user 打开 `/trade` 看到 `OrderForm.vue`
- **THEN** `价格类型` 段 MUST 渲染为独立全宽 `<el-form-item>`, 内含 `<el-radio-group class="price-type-grid">`
- **AND** MUST 渲染 2 行 × 2 列布局: `[限价 | 最新价]` 在上, `[挂单价 | 市价]` 在下
- **AND** 4 个 `<el-radio>` MUST 各占 grid cell 50% 宽度 (CSS `grid-template-columns: 1fr 1fr`)
- **AND** 每个 radio label (`限价` / `最新价` / `挂单价` / `市价`) MUST 完整可见（无 ellipsis 截断）
- **AND** `el-segmented` MUST NOT 在该 view 中出现 (DOM 不含 `.el-segmented` 节点)

#### Scenario: 委托价格独立全宽行渲染

- **WHEN** user 打开 `/trade` 看到 `OrderForm.vue`
- **THEN** `委托价格` 段 MUST 渲染为独立全宽 `<el-form-item>`
- **AND** MUST 与 `价格类型` 段垂直对齐（不共享 grid 行）
- **AND** MUST NOT 含 `.price-row` / `.price-col` 包裹 DOM

#### Scenario: 委托数量保持独立全宽行

- **WHEN** user 打开 `/trade` 看到 `OrderForm.vue`
- **THEN** `委托数量` 段 MUST 仍为独立全宽 `<el-form-item>` (与 `委托价格` 对称, 中间无 grid 容器)

#### Scenario: DOM 不含旧价格行容器

- **WHEN** 浏览器渲染 `OrderForm.vue`
- **THEN** 渲染出的 DOM 中 MUST NOT 出现 `.price-row` 节点
- **AND** MUST NOT 出现 `.price-type-col` / `.price-col` class 包裹元素

#### Scenario: 行为不变

- **WHEN** user 切换 `价格类型` (`限价` / `最新价` / `挂单价` / `市价`) 或输入 `委托价格` / `委托数量`
- **THEN** `form.price_type` / `form.price` / `form.volume` 响应式行为 MUST 与改造前完全一致
- **AND** `handleSubmit` 校验 / `ElMessageBox.confirm` / `props.onSubmit` 调用 MUST 不变
- **AND** radio-group `v-model` 单选互斥 MUST 生效 (任一时刻仅 1 项 checked)

### REQ-FE-012: 移除前端 fall-back 兼容 key（v11）

**Removed**（v11 起不再需要）：
- 14 个英文 fall-back key（`unreported` / `pending_report` / `reported` / `reported_cancel` / `partial_pending_cancel` / `partial_cancelled` / `cancelled` / `partial` / `filled` / `rejected` / `unknown` / `pending` 等）是历史 in-memory 状态遗留
- `grep -rE "STATUS_LABEL\['(unreported|pending_report|reported|...)\]'\]" client/src/` 0 处外部引用
- 与 broker xtconstant 字典对齐后无业务价值（broker 字典只有数字字符串 key）
- 1-2 年前遗留，无第三方引用，删 0 风险

**Migration**:
- 删除 `client/src/utils/format.js` 的 `STATUS_LABEL` / `STATUS_TYPE` / `STATUS_TONE` / `STATUS_ICON_NAME` / `STATUS_PULSE` 5 张字典中所有英文 fall-back key 段
- 仅保留 broker xtconstant 字典 11 条（48-57 + 255）
- 视图层（Trade.vue / Orders.vue / TradeStatusBadge.vue）只读 5 张字典的 broker 码 key，不读英文 fall-back key

#### Scenario: 删除 fall-back 兼容 key

- **WHEN** 静态扫 `client/src/utils/format.js`
- **THEN** `STATUS_LABEL` / `STATUS_TYPE` / `STATUS_TONE` / `STATUS_ICON_NAME` / `STATUS_PULSE` 5 张字典只含 11 条 broker xtconstant 码 (48-57 + 255)
- **AND** 14 个英文 fall-back key (unreported / pending_report / reported / ...) 全部删除

### REQ-FE-050: T0Trade.vue 拆分（phase-2 初版 — composable 抽取）

- **背景**: v1-v9 多轮迭代后 `views/T0Trade.vue` 长 1819 行，混合 SVG 几何 / 下单 / 风险档位 / 抽屉 / 卡片渲染等职责
- **拆分（已落地）**:
  - `client/src/composables/useT0ChartGeometry.js` (~145 行)
    - `useT0ChartGeometry(cumHistory, {W,H,pad})` — 主表 SVG 几何（含 barX/barY/xLabelIndices）
    - `useT0DrawerChartGeometry(cumHistory, {W,H,pad})` — 抽屉 chart 几何（紧凑版）
    - 消除主表 chart + drawer chart 60 行重复
  - `client/src/composables/useT0OrderSubmit.js` (~66 行)
    - `useT0OrderSubmit({stockCode, priceType, balanceCoeff, submitting, orderStore, onAfterSuccess})` 工厂
    - 返回 `{ submitOrder({orderType, volume, price}) }`
    - 内部:价格类型映射、orderStore.placeOrder、ElMessage 成功/错误码分支
- **保留在 T0Trade.vue**（未拆出）:
  - 8 个 el-card section（QuickSettings/PositionTable/DetailDrawer/MetricCards/Exposure/Action/Risk/History）
  - on*Buy / on*Sell / on*Balance / onRebalanceXxx（短函数,与本地 ref/computed 强耦合）
- **行数变化**: 1819 → 1704 (-115)
- **后续拆 component 候选**（留作 phase-3）:
  - `components/t0/DetailDrawer.vue`（抽屉,94 行 template + 50 行 state）
  - `components/t0/RiskProfileCard.vue`（仓位建议卡 + 4 档 radio）
  - `components/t0/HistoryChart.vue`（SVG 曲线展示）
- **契约**:
  - composable 通过依赖注入 refs/stores,不持有内部 state
  - SVG path 字符串格式与原版逐字符等价（测试用 `eq` 而非 visual diff）
  - submitOrder 错误码分支保留（TRADING_DAY_NOT_INIT / OUTSIDE_TRADING_SESSION / 其他）

### REQ-FE-051: Users.vue 拆分（phase-2）

- **背景**：v1-v8 多轮迭代后 `views/Users.vue` 长 719 行，混合 5 类职责（统计 / 筛选 / 表格 / 弹窗 / 业务方法）
- **拆分后**：
  - `client/src/views/Users.vue` (438) — 主壳：概览 stats row + 筛选 + 表格 + 分页
  - `client/src/composables/useUserActions.js` (219) — 弹窗状态 + 业务方法（openCreate / openEdit / submitEdit / openResetPwd / submitResetPwd / toggleActive / confirmDelete）
  - `client/src/components/users/UserEditDialog.vue` (109) — 新建/编辑弹窗
  - `client/src/components/users/UserResetPwdDialog.vue` (123) — 重置密码弹窗
- **契约**：
  - dialog 内部自管 formRef + watch(visible) 自动 clearValidate
  - composable 持有弹窗 state，通过 `actions.editDialogRef = editDialogEl` 挂 dialog instance，submit 时调 `dialog.validate()`
  - dialog 通过 `defineExpose({ formRef, validate })` 暴露
  - Users.vue 主壳不再含 dialog 模板，结构清晰：表格 + 2 个 dialog
- **向后兼容**：21 个 view 已有 `useHoldingsStore` 等不动；Users.vue 路由 `/users` 行为不变
  - `el-input-number` 属性：`precision=2`, `step=0.01`
  - 提交时 `form.price` 已是 float，直接走 `OrderOut.price: float` 后端 schema
- **非限价单**（市价/最新价/挂单价）：input disabled，precision 无实际作用

### Known Issues (from analysis)

- 🟡 `TStrategy.vue` / `AlgoStrategy.vue` 各 43 行，**未实现内容**
- 🟡 `auth.js` store 应该在 401 时自动清 token + 跳 login，目前**依赖** axios 拦截器调用 `setUnauthorizedHandler`
- 🟥 ~~Trade.vue 撤单按钮传 `order_id`~~ → **本轮已修**（change `2026-06-16-trade-page-show-order-no-and-cancel`，改传 order_no + trd_date）
- 🟥 ~~Trade.vue / Orders.vue 用 broker 原始 status 码分组~~ → **本轮已修**（change `2026-06-16-frontend-infer-order-status`，改本地推断码 + 镜像推断）
- 🟥 ~~Trade.vue 今日委托表无 order_no 列~~ → **本轮已修**（同上 change）
- 🟢 UI 偏好已沉淀到 user memory，UI 改动前先查
- 🟢 ~~前端 5s 轮询 fetchOrders + 缓存双源（orderStore/holdings）~~ → **v8 已修**（change `2026-06-21-order-push-trd-date-authority`，统一 holdings 单一源 + 删 5s 轮询改手动刷新）
- 🟢 ~~T0Trade.vue submitOrder 误读 res.code 永远走 else 分支~~ → **v8 已修**（同上 change，submitOrder 改 orderStore.placeOrder）
- 🟢 ~~ws.test.js / useT0Balance.test.js 10 个预存失败~~ → **未修**（独立 issue，与 v8 改造无关）

### REQ-FE-300: IDB 持久化模块契约（v14 fix-idb-store-missing-on-upgrade）

`client/src/stores/holdings_idb.js` 提供委托 / 成交 当日数据 IDB 持久化，**仅 orders / trades**，**不影响** positions / asset。

#### Scenario: 模块公开 API

- `initIDB()` —— 打开 `EvTrade-holdings-cache` (version=**3**), 含 `orders` / `trades` 两个 object store
  - 单例：同进程内多次调用复用同一 IDBDatabase
  - reject 时不抛（向上 throw 给调用方，由 caller 决定降级策略）
- `saveOrdersForDate(trdDate, orders)` —— **fire-and-forget** PUT `orders[trdDate] = JSON.parse(JSON.stringify(orders || []))`
  - 内部 try/catch + `console.warn`，**不抛异常**
  - `trdDate` 空字符串/null → noop
- `loadOrdersForDate(trdDate)` —— `Promise<Array | null>`，IDB miss 返 null
  - `trdDate` 空字符串/null → 立即 `null`
- `saveTradesForDate(trdDate, trades)` —— 同上 orders
- `loadTradesForDate(trdDate)` —— 同上 orders
- `clearDate(trdDate)` —— `Promise<void>`，删除 `orders[trdDate]` + `trades[trdDate]`（跨日切换调用）
- `_resetForTests()` —— 仅测试用，重置 module-level 单例

#### Scenario: IDB 写异常不外抛（critical path 不被 IDB 卡住）

- **WHEN** `saveOrder` / `saveTrade` 内部 IDB put 抛错（quota exceeded / 浏览器隐私模式 / navigator.storage undefined）
- **THEN** 函数 catch + `console.warn('[IDB] saveOrder/saveTrade failed:', ...)`
- **AND** 调用方（bootstrap / push handler）不需要 try/catch

#### Scenario: 升级路径 store 重建（v14 fix）

- **WHEN** IDB upgrade fires (oldV < 3, 含 fresh install 0→3 或 v12→v13→v3)
- **THEN** 升级回调 MUST 在 `deleteObjectStore(STORE_ORDERS|TRADES)` (当存在) 后**立刻显式 `createObjectStore`** -- 即使 openDB 包装已有 auto-create-if-missing 循环, 用户回调 delete 后仍需兜底 create
- **AND** DB 升到 v3 后 MUST 必含 `orders` / `trades` 两个 object store (即使之前 v2 因 bug 而 store 缺失, v3 升级触发即可 self-heal)
- **AND** 后续 `_loadByDate` 调用 MUST NOT 抛 `NotFoundError: object stores was not found` (除非运行时外部误删)

#### Scenario: 与 ws push 双写契约

- **WHEN** ws `order_update` / `trade_update` 触发 `applyOrderPush` / `applyTradePush`
- **THEN** Pinia ref 更新 + `saveOrdersForDate(activeDay, orders.value)` / `saveTradesForDate(activeDay, trades.value)` 异步调用
- **AND** `activeDay` 未就绪（null）→ save 自动 noop（getter 内 short-circuit）

#### Scenario: bootstrap IDB 优先

- **WHEN** `_resolveActiveDay()` 完成 → `activeTrdDate = "20260704"`
- **THEN** 立刻并行 `loadOrdersForDate("20260704")` + `loadTradesForDate("20260704")`
- **AND** 双命中 → 立刻写 Pinia `orders.value = cached` + `trades.value = cached`
- **AND** `refCounts.orders/trades = 'ok'` 立即标记
- **AND** 不再发 `/api/orders?trd_date=20260704`（spec 设计意图：today 页面用 IDB 即可，不再二次拉）

#### Scenario: IDB miss / 跨日降级

- **WHEN** IDB miss（首次启动 / 新交易日）或 `activeTrdDate` 未就绪
- **THEN** bootstrap 走原路径：拉 `/api/orders` + `/api/trades` 30 天窗口
- **WHEN** 跨日（IDB.trd_date !== active_day）
- **THEN** `clearDate(yesterday)` + 走 RPC fallback

#### Scenario: bootstrap 完成后 fire-and-forget 写 IDB

- **WHEN** `bootstrap()` 或 `refreshAll()` 完成 orders / trades 写入
- **THEN** 立刻 `saveOrdersForDate(activeDay, ...)` + `saveTradesForDate(activeDay, ...)`
- **AND** 即使 IDB 不可用也不影响加载流程（warn 后继续）

### REQ-FE-200: T0Trade 重新设计（中量行内仪表）

- **背景**：原页面 1704 行，主表只占视口 25%，下方 7 个堆叠卡片（敞口/T0 成本/预期收益/exposure-card/一键动作/配平计算/仓位建议），数据大量重复
- **严重 bug**：一键动作卡硬编码 600519.SH 茅台，与当前操作标的无关
- **新布局**：
  - Header + 设置条（标题右侧：仓位% + 价格档 + 刷新按钮）
  - 主表占视口主体，列：代码/名称/持仓/现价/涨跌/**今盈**/**净敞口**/**浮盈%** / 操作
  - 副行（expand 展开）：成本/成本额/今笔/胜率/30天 mini-sparkline
  - 操作列 4 按钮：买X%（绿）/ 卖X%（红）/ 配±N（橙，动态文本"配+200"/"配-200"，0 净敞口灰显）/ 详情→
  - 底部累计曲线（80px 高，按当前选中标的，7/30/90D 切换）
  - 右侧抽屉保持（历史曲线 + 累计统计 + 30 日明细）
- **删除项**：3 metric-card（敞口/T0 成本/预期收益）、exposure-card、一键动作卡（600519 硬编码）、配平计算卡、仓位管理建议卡、底部重复累计曲线
- **保留**：useT0OrderSubmit / onQuickBuy/Sell/Balance / holdingsStore.refreshPositions / 抽屉
- **移动端**（≤768px）：副行 sparkline 隐藏，曲线压缩到 60px
- **行数**：1704 → 823（-52%）

### Requirement: QuotePanel 按行情模板.png 重排版（卖盘纵栈 + 买盘纵栈 + 16 格 stats）

The system SHALL 让 `client/src/components/QuotePanel.vue` 渲染顺序与布局
对照 broker 终端 `行情模板.png` 重排：

- 头部：股票名 + 股票代码（其上方有"涨跌状态标识" -- 当前 v15 用 Symbol 按涨/跌/平显示 `▲`/`▼`/`▬`）, **r3**: 股票代码字号 18px + `font-weight: 600`
- 最新价 hero：大字号最新价 + 涨跌额 + 涨跌幅（涨红跌绿）, **r3**: hero 整行可点击带价
- ~~委比/委差 row~~ **(r3 移除)**
- 卖盘纵栈 5 行（档位 ↓ 价格 ↓ 量），顺序 `卖5` → `卖1`（卖5 在顶）
- ~~中间最新价浮标~~ **(r3 移除, hero 已显示最新价, 重复)**
- 买盘纵栈 5 行，顺序 `买1` → `买5`（买1 在顶）
- 16 格 stats grid（8 行 2 列，**label 在左 / 数值在右**），按顺序 **(r3 Row1 改)**：
  `[昨收, 开盘]`, `[涨跌, 最高]`, `[涨幅, 最低]`, `[振幅, 均价]`,
  `[现手, 金额]`, `[总手, 量比]`, `[涨停, 跌停]`, `[市值, 费率]`
- **r3 价格格全部可点**: hero + 卖/买 5×2 价 + stats 7 个价格格 (昨收/开盘/最高/最低/均价/涨停/跌停) 共 18 个 emit 点

数字不可计算 / 后端未提供时 MUST 显示 `—` 而不是隐藏 (布局稳定)。

#### Scenario: 头部标的与最新价 hero 渲染

- **WHEN** `OrderForm` 输入了有效 stock_code 且 quote ws push 已到
- **THEN** `QuotePanel.vue` 顶部 MUST 渲染 `名+码` (Symbol ▲/▼/▬ + 股票名 + 空格 + 股票代码)
- **AND** 股票代码 MUST 字号 18px + `font-weight: 600` (r3)
- **AND** 大最新价 + 涨跌额 + 涨跌幅 MUST 在同一行展示, 颜色按 `text-up` 涨红 / `text-down` 跌绿 / `text-flat` 平黑
- **AND** hero 整行 MUST 可点击带价 (r3): `@click="emitApply(lastPrice)"` + `is-clickable` 类 + `title="点击带入委托价"` + hover 态 `var(--bg-hover)`

#### Scenario: ~~委比/委差 row 计算并展示~~ — r3 移除

- **r3 状态**: 不再渲染。trader 反馈: 后端 5 档口径与全档口径有差异, 视觉冗余。`script setup` 中 `committeeDiff` / `committeeRatio` / `sumAskVol` / `sumBidVol` helper 已删除。

#### Scenario: 卖盘纵栈 5 行渲染

- **WHEN** quote ws push 含 askPrice[1..5]
- **THEN** MUST 渲染 5 行 sell, 顺序 `卖5` (顶) → `卖1` (底)
- **AND** 每行 MUST 含 `档位` (左) / `价格` (中) / `量` (右, 整数千分位)
- **AND** 缺档位时 MUST 显示 `—` (不塌陷行)

#### Scenario: 买盘纵栈 5 行渲染

- **WHEN** quote ws push 含 bidPrice[1..5]
- **THEN** MUST 渲染 5 行 buy, 顺序 `买1` (顶) → `买5` (底)
- **AND** 每行 MUST 含 `档位` / `价格` / `量`, 缺档位显示 `—`

#### Scenario: 16 格 stats grid 渲染

- **WHEN** `QuotePanel.vue` 渲染于正常数据状态
- **THEN** MUST 渲染 8 行 × 2 列 = 16 格 grid, label 左值右
- **AND** 字段 MUST 按顺序 **(r3 Row1 首格改)** `昨收 / 开盘 / 涨跌 / 最高 / 涨幅 / 最低 / 振幅 / 均价 / 现手 / 金额 / 总手 / 量比 / 涨停 / 跌停 / 市值 / 费率`
- **AND** 已计算的字段 MUST 填实:
  - `均价 = amount / volume` (除 0 显示 `—`) — **r3 可点击**
  - `振幅 = (high - low) / prevClose * 100%` (prevClose=0 显示 `—`)
  - `涨停 = prevClose * 1.10` (2 位小数) — **r3 可点击**
  - `跌停 = prevClose * 0.90` (2 位小数) — **r3 可点击**
  - `昨收` = `fields[PREV_CLOSE]` — **r3 可点击**
  - `开盘` = `fields[OPEN]` — **r3 可点击**
  - `最高` = `fields[HIGH]` — **r3 可点击**
  - `最低` = `fields[LOW]` — **r3 可点击**
- **AND** 未计算的字段 (`现手` / `量比` / `市值` / `费率`) MUST 显示 `—`

### Requirement: QuotePanel 单击价格带入 OrderForm 委托价（替代双击; r3 覆盖 18 个 cell）

The system SHALL 让 `client/src/components/QuotePanel.vue` 中

> **改前**（v15 之前）：卖盘/买盘 cell / 6 格 cell 用 `@dblclick="emitApply(...)"` 触发价格带入
> **改后**（v15）：改用 `@click="emitApply(...)"`，鼠标 hover 态有视觉提示 (cursor + bg color + title tooltip)
> **r3 扩展**：覆盖 18 个 price cell (hero 1 + 卖 5 + 买 5 + stats 7 = 18); 非价格的 cells (涨跌/涨幅/振幅/金额/总手/现手/量比/市值/费率) 保持静态

行为约束：
- 卖 1..卖 5 / 买 1..买 5 任一档位的"价格"列 MUST 单击即向父组件 `Trade.vue` emit `apply-price` 事件
- hero 大最新价 MUST 单击可带入 (r3)
- 7 个 stats 价格格 (`昨收 / 开盘 / 最高 / 最低 / 均价 / 涨停 / 跌停`) MUST 单击可带入 (r3)
- emit payload MUST 为数字 (Number 类型, 保留原始精度)
- 鼠标 hover 任一可点击 cell MUST 变更 background 至 `var(--bg-hover)` + `cursor: pointer` + `title="点击带入委托价"`
- 非价格格 (涨跌/涨幅/振幅/金额/总手/未计算字段) MUST NOT 触发 emit (无 cursor: pointer, 无 hover 态)

#### Scenario: 单击卖 1 价带入 OrderForm

- **WHEN** user 鼠标 hover 卖盘第 `卖1` 行价格列
- **THEN** background 变 `var(--bg-hover)` + cursor `pointer`
- **WHEN** user click 卖 1 价格 cell
- **THEN** MUST emit `apply-price` 事件, payload = `Number(askPrice[0])`
- **AND** Trade.vue 调用 `onApplyPrice` → `orderStore.setPrice(price)` → OrderForm `form.price` 更新

#### Scenario: 单击买 3 价带入 OrderForm

- **WHEN** user click 买 3 价格 cell
- **THEN** MUST emit `apply-price`, payload = `Number(bidPrice[2])`

#### Scenario: 单击 hero 最新价带入 OrderForm (r3)

- **WHEN** user 鼠标 hover hero 整行
- **THEN** background 变 `var(--bg-hover)` + cursor `pointer`
- **WHEN** user click hero (任意位置)
- **THEN** MUST emit `apply-price`, payload = `Number(lastPrice)`

#### Scenario: 单击 stats 昨收 / 开盘 / 最高 / 最低 / 均价 / 涨停 / 跌停 价带入 OrderForm (r3)

- **WHEN** user click stats grid 中 `昨收` / `开盘` / `最高` / `最低` / `均价` / `涨停` / `跌停` 任一 cell
- **THEN** MUST emit `apply-price`, payload 对应 `prevClose` / `open` / `high` / `low` / `avgPrice` / `limitUp` / `limitDown` 数字

#### Scenario: 缺档位时不可点击

- **WHEN** 卖/买某档缺价 (null / 0) 或 stats 价格格字段未提供 (null / 0)
- **THEN** 该 cell MUST NOT 渲染 `cursor: pointer` 且 click MUST NOT emit (内部 `emitApply` 已对 null/0 早返)

#### Scenario: 非价格格 (涨跌/涨幅/振幅/未支持) 不可点击

- **WHEN** user hover stats grid 中 `涨跌` / `涨幅` / `振幅` / `现手` / `量比` / `市值` / `费率` cell
- **THEN** MUST NOT 变更 background + MUST NOT 显示 `cursor: pointer`
- **AND** click MUST NOT emit

### REQ-FE-210: T0Trade 主表 polish bundle (t0-trade-polish-bundle)

主表快速操作 (买/卖/配平/详情) 5 项 polish, 单 change 多 commit 实施.

#### Scenario: 资金/持仓校验 disabled (commit 2)

- **WHEN** user 在主表 hover 买按钮且 cash < qty × price (走 lib/t0-calc.calcInsufficientCash)
- **THEN** MUST 显示 tooltip "资金 ¥X.XXw 不足 (需 ¥X.XXw, 现有 ¥X.XXk)" + MUST 禁用按钮
- **AND** 持仓不足卖时 MUST 显示 "持仓 X 股不足, 缺 Y 股"
- **AND** 配平按钮按 side 分别查 cash (买) / 持仓 (卖), tooltip 注明

#### Scenario: t0Stats 30s TTL 缓存命中 (commit 3)

- **WHEN** 主表 30 持仓, 30s 内重复访问同一 stock_code
- **THEN** MUST 只在首次 fetch, 后续命中 useT0Stats 模块级 Map 缓存
- **AND** ws 委托/成交推送 MUST 触发 useT0Stats.invalidate(stock_code)
- **AND** 跨日切换 MUST 触发 useT0Stats.invalidateAll()

#### Scenario: 排序点击表头响应 (commit 5)

- **WHEN** user click 主表 6 列 (持仓/现价/涨跌/今盈/净敞口/浮盈%) 表头
- **THEN** MUST 切 `sortable="custom"` 排序方向 (asc/desc), sortedRows computed 派生
- **AND** selectedRowCode 按 sortedRows 顺序切换 (排序变化时 stockCode 不变性)

#### Scenario: 快捷键触发对应行操作 (commit 5)

- **WHEN** user 按 B (买) / S (卖) / P (配平) 键, uiStore.t0Keybindings === true, drawerVisible === false
- **THEN** MUST 触发 selectedRow 的 onQuickBuy/Sell/Balance
- **AND** ↑↓ MUST 切 selectedRowCode, Enter MUST 开抽屉
- **AND** 输入框 / textarea / select / contenteditable MUST 不触发
- **AND** 修键 (Ctrl/Meta/Alt) MUST 不触发

#### Scenario: 副行 hover popover 显示 30 日累计 (commit 4)

- **WHEN** user hover 副行"30天"字段
- **THEN** MUST 显示 D-1..D-30 倒序数值列表 (lazy load via @show)
- **AND** 移动端 (< 768px) MUST 静态隐藏 popover (避免 hover 不工作)

### REQ-FE-310: 策略交易路由 + 角色守卫（strategy_trade）

- **`/strategy-trade` 路由**：`client/src/views/StrategyTrade.vue` 主视图（左侧 StrategyList + 编辑表单 / 右侧 StrategyMonitor）
- **角色守卫**：`meta.requiresTrader = true`（trader 或 admin 可访问）
- **旧路由重定向**：`/algo-strategy` → `/strategy-trade`（旧书签兼容）
- **WS 频道**：在 `ws_heartbeat.js::CHANNELS` 加 `'strategy_update'`，由 `ws_dispatch.js::_onStrategyUpdate` 分发到 `useStrategyStore().appendAudit`
- **导航栏入口**：Sidebar.vue 加 `/strategy-trade` 链接

#### Scenario: trader 访问 /strategy-trade

- **GIVEN** role=trader
- **WHEN** router push /strategy-trade
- **THEN** MUST 渲染 StrategyTrade 视图

#### Scenario: 非 trader 访问 /strategy-trade

- **GIVEN** role ≠ trader 且 ≠ admin
- **WHEN** router push /strategy-trade
- **THEN** MUST 重定向到 /

#### Scenario: 旧 /algo-strategy 重定向

- **WHEN** router push /algo-strategy
- **THEN** MUST 重定向到 /strategy-trade

#### Scenario: strategy_update WS 推送到 audit cache

- **WHEN** 收到 WS payload `type='strategy_update', data.strategy_id=5`
- **THEN** MUST 包装为 AuditRecord 推入 `store.auditCache[5][trd_date]`
- **AND** 缺 strategy_id MUST 静默丢弃

### REQ-FE-510: OrderForm 价格类型单行布局 (2026-07-09 重构, 与 T0 一致)

The system SHALL render `client/src/components/OrderForm.vue` 的价格类型选择器为单行 inline radio-button,与 T0Trade 页面的「价格档」视觉风格一致。

#### Scenario: 桌面端 4 个选项排在一行

- **GIVEN** 用户在 Trade.vue 打开 OrderForm,视口宽度 ≥ 1024px
- **WHEN** 渲染价格类型选择器
- **THEN** 4 个选项(限价 / 最新价 / 挂单价 / 市价)以 `el-radio-button` 单行排布
- **AND** 选中态、悬停态沿用 Element Plus 默认 button 样式,无需自定义 grid

#### Scenario: 窄屏自动换行降级

- **GIVEN** 用户在窄屏(视口 < 720px)打开 OrderForm
- **WHEN** 4 个 default-size 按钮宽度超过容器
- **THEN** 沿用 `el-radio-group` 默认 `flex-wrap: wrap`,自动换行(可能 2 行)
- **AND** 不影响选中/提交逻辑

#### Scenario: 数据绑定不变

- **GIVEN** `v-model="form.price_type"` 与 `form.price_type` 联动委托价格 input 的 `disabled` / `placeholder` / `PriceType.FIX_PRICE` 校验
- **WHEN** 用户切换价格类型
- **THEN** 委托价格 input 的禁用条件与 placeholder 保持原行为
- **AND** 后端 API 调用协议 `{price_type: 0|1|2}`（v__: 与 xtconstant 柜台协议 1:1 对齐）

### REQ-FE-520: StockCodeAutocomplete 左右拆分两半（v27 重构, 2026-07-13）

The system SHALL render `client/src/components/StockCodeAutocomplete.vue` 为左右两个独立区域:
- **左半 (50%)**: `el-autocomplete` 股票代码输入 + 候选下拉 (可编辑, 支持 stock_code / stock_name / short_name 检索)
- **右半 (50%)**: `disabled el-input` 证券名称展示 (只读, 不可手动改)

证券名称 SHALL 通过 `watch(() => props.modelValue, ...)` 监听 modelValue 变化, 从 `useStocksStore().cache` 中匹配 `stock_code === newVal` 自动回填; 命中失败则清空 (强制用户重新选择有效股票代码, 满足 v25 用户硬性偏好)。

#### Scenario: 选中候选后名称自动加载

- **GIVEN** 用户在 Trade.vue / T0Trade / StrategyConfig / AdminStockConfig 任一页面
- **WHEN** 在左半 autocomplete 输入 "600519" 并从候选下拉选中 "600519.SH 贵州茅台"
- **THEN** 父组件 `modelValue` 同步为 `"600519.SH"` (纯 stock_code, 不含名称)
- **AND** 右半 disabled input 自动显示 "贵州茅台" (来自 watch → cache 查找)

#### Scenario: 修改代码 → 名称清空 → 强制重选

- **GIVEN** 用户已选中 600519.SH, 右半显示"贵州茅台"
- **WHEN** 用户点击左半 clear 图标 (X 按钮) 清空 modelValue, 或手动输入新代码"000001"
- **THEN** 右半 disabled input MUST 清空 (displayName.value = '')
- **AND** 当用户重新从候选下拉选中 "000001.SZ 平安银行" 后, 右半自动显示"平安银行"

#### Scenario: modelValue 语义收紧 (v27)

- **GIVEN** v26 之前 `modelValue` 可能是 "600519.SH 贵州茅台" (代码+名称拼接)
- **WHEN** v27 重构完成
- **THEN** `modelValue` MUST 仅为 stock_code 字符串 ("600519.SH" / "000001.SZ" 等)
- **AND** OrderForm / T0TaskCreateDialog / StrategyConfig / AdminStockConfig 等调用方 MUST 通过 `@select="onAutocompleteSelect"` 回调从 `item.stock_name` 显式写 `form.stock_name`, 不依赖拼接字符串 split

#### Scenario: 候选列表仍然显示代码+名称+拼音首字母

- **GIVEN** v27 重构
- **WHEN** autocomplete 候选下拉渲染
- **THEN** 候选项 MUST 仍显示 "stock_code + stock_name [+ short_name]" 三段式 (sca-row 模板保留)
- **AND** 右半 disabled input 不重复显示名称到候选列表里 (候选列表本身就是名称的载体)

#### Scenario: 父组件 stock_name 数据流

- **GIVEN** OrderForm.vue 通过 `<StockCodeAutocomplete v-model="form.stock_code">` 接入
- **WHEN** 用户选中候选
- **THEN** `form.stock_code = item.stock_code` (走 v-model 双向绑定)
- **AND** `form.stock_name = item.stock_name` (走 @select 显式写入, OrderForm 不依赖 StockCodeAutocomplete 内部 displayName)
- **AND** StockCodeAutocomplete 的右半 displayName 是 UI 展示态, 不作为业务数据源

#### Scenario: 禁用 stockCodeAutocomplete 的 props.modelValue 不可写

- **GIVEN** StockCodeAutocomplete 右半 el-input 设置 `disabled`
- **WHEN** 用户尝试点击/编辑右半
- **THEN** 浏览器 MUST 阻止编辑 (native disabled 属性)
- **AND** 名称来源唯一 = watch → cache 查找; 不接受外部 prop 覆盖 (避免双源不一致)

### REMOVED Requirements

#### Requirement: QuotePanel 双击价格带入（v15 之前行为）

**Reason**：v15 改单击, 双击与单击并存会让用户困惑; 单击节奏更短, 符合 trader "看价 → 点 → 下单" 的快节奏。

**Migration**：
- 删 `client/src/components/QuotePanel.vue` 中所有 `@dblclick="emitApply(...)"` 的模板节点
- 改为 `@click="emitApply(...)"`, tooltip `title` 改为 "点击带入委托价"
- Trade.vue `@apply-price="onApplyPrice"` 监听器不变, emit 协议不变

#### Requirement: QuotePanel 委比 / 委差 row 渲染（v15 首次实现）— r3 移除

**Reason**：trader 反馈: 1) 后端 5 档口径与全档口径不一致, 显示值易误导; 2) hero 已显最新价 + 涨跌/涨幅, 委比/委差视觉冗余。

**Migration**：
- 删 `<div class="qp-committee">` 模板块
- 删 `.qp-committee` CSS 块
- 删 `<script setup>` 中 `committeeDiff` / `committeeRatio` / `committeeDiffText` / `committeeRatioText` 4 个 computed + `sumAskVol` / `sumBidVol` 2 个 helper
- Trade.vue 不消费这两个字段, 无下游影响

#### Requirement: QuotePanel 卖 1 / 买 1 中间最新价浮标（v15 首次实现）— r3 移除

**Reason**：hero 已显示最新价, 中间浮标重复; 且移除后视线直"卖压 → 买力", 更紧凑。

**Migration**：
- 删 `<div class="qp-mid">` 模板块
- 删 `.qp-mid` / `.qp-mid-label` / `.qp-mid-price` CSS 块
- 卖盘栈与买盘栈之间不留空 row, 直接堆叠

#### Requirement: T0Trade 副行 mini-sparkline（v16 首次实现）— t0-trade-polish-bundle commit 4 移除

**Reason**：与底部 7/30/90D 曲线是同一数据 2 次绘制; 副行占视觉空间但 trader 仅在 hover 才看趋势; 移动端 hover 不工作, 静态隐藏反而误导。

**Migration**：
- 删 `client/src/views/T0Trade.vue` 中 `<svg.mini-sparkline>` 150x30 SVG + `sparklinePoints` / `sparklinePath` / `sparklineLast` / `loadSparkline` 4 函数
- 副行 30 天改为 `<el-popover trigger="hover">` reference "¥{last} ↑/↓" + content D-1..D-30 倒序
- CSS `@media (max-width: 768px) .sub-popover { display: none }`

#### Requirement: OrderForm 价格类型 2×2 grid 布局 (2026-07-09 重构前设计, 已废弃)

**Reason**: Trade 页价格档采用 2×2 grid (`.price-type-grid` + `el-radio` with `border`), 视觉占用一整行 + 4 个 grid cell, 与 T0Trade 单行 inline radio-button 风格不一致; 4 个选项挤在网格里 label 显得小气, 不如单行按钮紧凑。

**Migration**:
- 改 `client/src/components/OrderForm.vue` 第 38-51 行 template: `el-radio-group + el-radio(border) + class="price-type-grid"` → `el-radio-group + el-radio-button(size="default")`
- 删 `client/src/components/OrderForm.vue` 第 364-386 行 `.price-type-grid` / `:deep(.price-type-grid .el-radio*)` 死 CSS
- 数据流不变 (`v-model="form.price_type"` + `PriceType.FIX_PRICE` 校验逻辑不动); 后端协议 `{price_type: 0|1|2}`（v__: 与 xtconstant 柜台协议 1:1 对齐）


### REQ-FE-INIT-001: 收到 init_completed 触发 store 刷新

- **WHEN** ws 收到 `{type:'init_completed', trd_date, report_id, status, ts}` payload
- **THEN** 前端 `client/src/stores/ws_dispatch.js::_onInitCompleted(data)` 触发：
  1. `useHoldingsStore().refreshAll()` — 并行 4 RPC（asset / positions / orders / trades）写缓存
  2. `useAssetStore().fetchAsset()` — 资金刷新（兼容老 view，holdings 已含 cachedAsset 但 store 桥接另算）
  3. `usePositionStore().fetchPositions()` — 持仓刷新（同上兼容）
- **AND** 不弹 toast / 不弹 Notification（静默刷新，与 AppHeader 按钮行为对齐）
- **AND** 失败由 `holdings.refreshAll()` 内部 refCounts 守门，不抛异常到 UI
- **AND** SystemInit.vue::handleInit 收到 HTTP 200 后**也**直接调一次 refreshAll（双保险，不依赖 ws 推送成功）

#### Scenario: init_completed 全量刷新

- **WHEN** 后端推 init_completed (status='ok')
- **THEN** 持仓页 / 资金页数字立即更新（无需点 AppHeader 刷新按钮）

#### Scenario: 双保险 — HTTP 200 同步刷新 + ws 推送

- **WHEN** SystemInit.vue::handleInit 收到 HTTP 200
- **THEN** **也**直接调一次 refreshAll（不依赖 ws 推送成功）
- **AND** ws init_completed 到达后**再**调一次 refreshAll（最终一致性）
- **AND** 两次 refreshAll 内部幂等（refCounts 已就位时跳过）

#### Scenario: ws 未连接 / 推送丢失

- **WHEN** 用户 ws 断开（refreshAll 已弹错）
- **THEN** handleInit 同步刷新路径保证持仓页更新
- **AND** 下次 ws 重连后 init_completed 不会重放（fire-and-forget，无重试）

### REQ-FE-STOCK-CREATE: 证券信息设置支持添加证券 (v46 stock-info-create)

**位置**: `/admin/stock-config` 页面 (`client/src/views/AdminStockConfig.vue`)  
**入口**: panel-header 新增 `添加证券` 按钮（Primary type，紧邻 `刷新` 按钮）  
**可见性**: 仅 admin 角色可见（菜单层 + `require_admin` API 拦截双保险）

**对话框契约**（`el-dialog title="添加证券" width="520px"`）：

| Form 字段 | 控件 | 校验规则 |
|---|---|---|
| `stock_code` | `el-input` | 必填 + regex `^\d{6}\.(SH|SZ\|BJ)$`（与后端 Pydantic 对齐） |
| `stock_name` | `el-input` | 必填，max 64 |
| `sector` | `el-input` | 可选，max 64 |
| `short_name` | `el-input` | 可选，max 16 |
| `is_t0_able` | `el-switch` | 默认 false（`T+1`） |
| `min_buy_qty` | `el-input-number` | 默认 100，ge 1 |
| `trade_unit` | `el-input-number` | 默认 1，ge 1 |

**提交流程**（`onCreateSave`）：

1. `await createFormRef.value?.validate()` — element-plus 行内校验
2. 空字符串转 `null`（后端 Optional 字段友好）
3. `store.createStock(payload)` — 调用 `stocksApi.create` POST `/api/stocks`
4. **成功**: `ElMessage.success("已添加 999999.SH 测试证券1号")` + 关闭 dialog
5. **失败**: `ElMessage.error(r.msg)`（覆盖 422 / 409 / 500 全部场景）

**Store 同步**（`useStocksStore().createStock`）：

- `cache.value.unshift(data)` — 缓存头部插入（autocomplete 立即可用）
- `total.value += 1` — 顶部"全量缓存 N 条"和分页器"共 N 条"同步 +1
- 若 `page.value === 1`：`pageRows.value.unshift(data)` — 当前页立即显示
- `createLoading.value` 绑定到 dialog 添加按钮 loading 态

**关键设计**：

- **独立 dialog**: 与编辑 dialog 解耦，`createDialogVisible` 与 `dialogVisible` 分开
- **每次打开重置**: `emptyCreateForm()` + `createFormRef.clearValidate()`，防止上次的脏数据残留
- **`extra=forbid` 对齐**: v22 旧字段 `industry` / `market` / `intro` 在 Pydantic 即抛 422，前端不会发送
- **不开放删除**: v22 已决策，admin 误删不可逆。只能添加 + 编辑现有

#### Scenario: 成功添加证券

- **GIVEN** admin 已登录，`/admin/stock-config` 页面打开
- **WHEN** 点击 `添加证券` 按钮 → 填写 `999998.SH` + 名称 + 板块 + T+0 + 最小买入 → 点击 `添加`
- **THEN** 对话框自动关闭
- **AND** 表格第 1 行显示新加的 999998.SH
- **AND** 顶部"全量缓存 N 条"和分页器"共 N 条"都 +1
- **AND** `ElMessage.success` 提示"已添加 999998.SH ..."

#### Scenario: 重复 stock_code 走 409

- **GIVEN** `999998.SH` 已存在（来自上次添加或爬虫）
- **WHEN** admin 再次填相同 stock_code 并提交
- **THEN** 对话框保持打开（不关闭）
- **AND** `ElMessage.error` 提示 "stock 999998.SH already exists"
- **AND** 表格不变，total 不变

#### Scenario: 格式校验不通过

- **GIVEN** admin 输入 `stock_code="99999"`（缺后缀）
- **WHEN** blur 输入框（触发校验）
- **THEN** 输入框红色高亮 + 下方红字"格式必须是 6 位数字 + .SH/.SZ/.BJ"
- **AND** 添加按钮即使点击也走不到后端（element-plus validate 拦截）

### REQ-FE-STOCK-HIDE: 隐藏 short_name 编辑界面（v46+ short-name-auto）

**位置**: `client/src/views/AdminStockConfig.vue` (`/admin/stock-config` 页面)

**目的**: `short_name` 字段完全由后端自动生成，前端不展示、不接收、不传输。

**UI 变更**（v46+ vs v25）：
- ❌ **删除表格列**"首字母"`prop="short_name"`（之前 8 列 → 现在 7 列）
- ❌ **删除编辑对话框**"拼音首字母"`<el-form-item label="拼音首字母">`（input + maxlength=16 + show-word-limit）
- ❌ **删除添加对话框**"简称"`<el-form-item label="简称" prop="short_name">`（input + maxlength=16）
- ❌ **删除 form 默认值** `short_name: ''`
- ❌ **删除 form 校验规则** `short_name: [{ max: 16, ... }]`
- ❌ **删除提交 payload** `short_name: createForm.value.short_name.trim() || null`

**保留**（v46+）：
- ✅ **客户端 keyword 搜索**仍走 short_name 二次过滤（仅前端 cache 命中，不发请求）
  - 位置：`store.fetchFilteredStockList` 中 `const short = (s.short_name || '').toLowerCase()`（约 12597 行）
- ✅ **API 调用层** `stocksApi.create/update` payload 不再含 `short_name`（与 v46+ 后端 `extra=forbid` 对齐）

**契约**（v46+）：
- 表格 columnheader 集合：代码 / 名称 / 板块 / 回转标志 / 最小买入数量 / 买卖单位 / 操作（**7 列**，无"首字母"）
- 添加对话框 el-form-item 集合：证券代码（必）/ 证券名称（必）/ 所属板块 / T+0 / 最小买入 / 买卖单位（**6 项**，无"简称"）
- 编辑对话框 el-form-item 集合：板块 / 回转标志 / 最小买入 / 买卖单位（**保留 4 项**，无"拼音首字母" — 板块前移）

#### Scenario

- **GIVEN** admin 打开 `/admin/stock-config` 页面（无 short_name 缓存）
- **WHEN** 表格渲染
- **THEN** columnheader 集合不含"首字母"列（只有 7 列：代码/名称/板块/回转标志/最小买入/买卖单位/操作）

- **GIVEN** admin 点击"添加证券"按钮
- **WHEN** dialog 弹出
- **THEN** 可见 el-form-item 只有 6 项（**无"简称"项**）
- **AND** 表单提交 payload 不含 `short_name` 字段

- **GIVEN** admin 点击某行"编辑"按钮
- **WHEN** 编辑 dialog 弹出
- **THEN** 可见 el-form-item 没有"拼音首字母"项
- **AND** PATCH payload 不含 `short_name`

- **GIVEN** admin 在顶部搜索框输入 `PAYH`（之前短名命中过平安银行）
- **WHEN** 前端 cache 模糊匹配
- **THEN** "代码 / 名称搜索"过滤仍能命中（**前端保留 short_name 搜索能力**）
- **AND** 与"首字母列是否展示"无关（列隐藏但 search 维度保留）

- **GIVEN** admin 添加 stock_name="\*st康佳"（小写开头）
- **WHEN** 添加成功
- **THEN** 表格新行显示名称列"\*st康佳"（**保留原名大小写**）
- **AND** 表格不展示 short_name 但服务端 GET `/api/stocks/{code}` 返回 `short_name="*STKJ"`（自动归一）

---

## REQ-FE-220: T0Trade 主表重构（做T盈亏 / 敞口 / 期初配额 / 做T收益率%）

The system SHALL 重做 `client/src/views/T0Trade.vue` 主表布局，从"quota frame 账户级 5 pill + 副行展开 + drawer 抽屉 + 底部曲线"重构为"11 列精简单表 + 4 按钮操作列"。

### Scenario: 11 列结构（必含）

- **GIVEN** user enters `/quick-t0` view
- **WHEN** the page renders the position table
- **THEN** the table MUST contain exactly 11 columns in order:
  1. 代码 (width 100)
  2. 名称 (width 100)
  3. 持仓 (width 100, sortable on `vol`)
  4. **最新价(涨跌幅%)** (width 130, sortable on `last_price`) — 单列合并原"现价 + 涨跌"两列；`formatPriceAuto` 显示最多 4 位小数去尾 0
  5. **期初** (width 100) — 显示 `row.last_vol`
  6. **可买** (width 100, sortable) — `calcInitialQuota({last_vol}, {today_buy_volume}).maxBuyable`
  7. **可卖** (width 100, sortable) — `calcInitialQuota({last_vol}, {today_sell_volume}).maxSellable`
  8. **做T盈亏** (width 100, sortable) — `calcT0Pnl(today_buy_amount, today_sell_amount)`
  9. **做T收益率%** (width 110, sortable) — `calcT0ReturnRate({last_vol, cost_price}, {today_buy_amount, today_sell_amount})`
  10. **浮盈%** (width 100, sortable) — `holdingsStore.getReturnRate(code)` 保留（v53 兼容）
  11. **操作** (width 180 fixed right) — 4 按钮：买N% / 卖N% / 配平 / 详情

### Scenario: 可买 / 可卖基于期初持仓递减

- **GIVEN** a position with `last_vol=1000`
- **AND** user has bought `today_buy_volume=300` and sold `today_sell_volume=200`
- **WHEN** the table renders the row
- **THEN** 可买 = `max(0, 1000 - 300) = 700`
- **AND** 可卖 = `max(0, 1000 - 200) = 800`
- **AND** 已成交部分 (300 / 200) 自动减占用

### Scenario: 配平价格 = 对手盘价 (买→ask1, 卖→bid1)

- **GIVEN** row's `today_buy_volume - today_sell_volume = +200` （净买入敞口）
- **AND** quote has `ask_prices[0]=11.5` (卖1价) `bid_prices[0]=10.5` (买1价) `last_price=10`
- **WHEN** user clicks "配平" button
- **THEN** `resolveBalancePrice(row, 'sell', quote) = {price: 10.5, fallback: false}` 卖1价用于抵消多头敞口
- **AND** `quote.ask_prices[0]` 无效 (0/NaN) → fallback 到 `last_price` 并提示用户

### Scenario: 价格小数位最多 4 位去尾 0

- **GIVEN** row's last_price = `1.142` (3位小数 ETF)
- **WHEN** the latest price cell renders
- **THEN** display string is `"1.142"` （非 `"1.1420"`） 非 `toFixed(2)`
- **AND** 同样适用于 ETF `513050.SH` `0.909` 与 `002736.SZ` `10.27`

### Scenario: 做T盈亏 = 卖成交额 - 买成交额

- **GIVEN** today's stats: `today_buy_amount=1000`, `today_sell_amount=1500`
- **WHEN** the 做T盈亏 cell renders
- **THEN** display value = `+500` （正值红 / 负值绿）

### Scenario: 做T收益率% = 做T盈亏 / (期初持仓 × 持仓成本价)

- **GIVEN** `last_vol=1000`, `cost_price=10`, 卖 1500 - 买 1000 = +500
- **WHEN** the 做T收益率% cell renders
- **THEN** rate = `500 / (1000 * 10) = 0.05 = 5.00%`

### Scenario: 浮盈% 列保留 (v53 兼容)

- **GIVEN** Dashboard / Trade card 等位置需要 `holdingsStore.getReturnRate`
- **WHEN** `/quick-t0` 页面渲染
- **THEN** 浮盈% 列仍展示，与做T收益率% 共存 2 列
- **AND** `getReturnRate(code)` API 不变

### Scenario: 删除 (Non-Goals)

下列功能**不**在 REQ-FE-220 范围内（新需求**不**回退）：
- quota frame (5 个账户级 pill: 现金余量 / 冻结 / T+0 可用 / 今日盈亏 / 持仓市值) 已删除
- 副行 (`type="expand"`) + 30 天 popover 已删除
- 底部 `cumHistory` 曲线已删除
- 右侧 `drawer` 做T明细 (实时统计) 已删除（详情按钮从抽屉入口转移为最小功能）
- `<el-table-column prop="net_exposure" label="净敞口">` 列已删除
- `<el-table-column label="可买" prop="max_buyable">` 列改为基于 `last_vol` 递减算法（不再依赖 `useT0Quota.rowQuota`）
- `<el-table-column label="可卖" prop="max_sellable">` 同上

### 风险与验收

| 风险 | 验收 |
|---|---|
| `last_vol` 字段不存在于某些持仓（如旧 mock） | `formatNumber(row.last_vol ?? row.vol ?? 0)` 兜底 |
| `quote.bid_prices/ask_prices` 缺失 | `resolveBalancePrice` 内部 `?.` 链 + fallback `last_price` |
| 旧 `realized_pnl` 引用 | REQ-FE-220 不破坏 `server/api/t0_stats.py` 返回值，旧列在 Dashboard/Trade 等位置仍读 `t0StatsMap.code.realized_pnl`（API 未改） |
| `formatPriceAuto` 显示精度突变 | 已 unit-tested 6+ 用例（`client/tests/lib/t0-calc.test.js`） |

### 相关文件

- `client/src/lib/t0-calc.js`（新增 5 纯函数: `calcT0Pnl` / `calcExposure` / `calcInitialQuota` / `calcT0ReturnRate` / `resolveBalancePrice`）
- `client/src/lib/t0-calc.test.js`（新增 35 个单测用例覆盖 5 函数）
- `client/src/views/T0Trade.vue`（大重做 +155/-665 = 净减 510 行）
- `client/src/utils/format.js`（复用 `formatPriceAuto`，已存在）
- `client/src/composables/useT0Quota.js`（仅复用 `quotaLevel` 函数，删除整 hook 调用）

---

## REQ-FE-230: T0Trade 切到任务视角 + 添加任务 dialog 集成 HoldingsPanel

The system SHALL 重做 `client/src/views/T0Trade.vue` 从"持仓视角"（v54 11 列 holdings 表）切到"任务视角"（8 列 task 表 + 添加任务 dialog 嵌入 HoldingsPanel）。

### Scenario: 主表 8 列任务视角 (必含列)

- **GIVEN** user ...[truncated] 合计 8 列

### Scenario: 添加任务 dialog 嵌入 HoldingsPanel 联动

- **GIVEN** user 点 "添加任务" (header Primary 按钮)
- **AND** dialog v-model=visible=true，width=900px
- **WHEN** dialog renders
- **THEN** dialog body MUST 分 2 列 grid（左 .add-task-left 350px 嵌 HoldingsPanel，右 .add-task-right 520px 嵌 T0TaskCreateDialog inline）
- **AND** 左侧 HoldingsPanel MUST 提示"单击持仓行自动填充右侧股票代码"
- **AND** 数据源 MUST 复用 `useHoldingsStore().positions`（与 Trade.vue 同源）

### Scenario: HoldingsPanel 单击 select-stock 联动

- **GIVEN** dialog 已开 + HoldingsPanel 渲染持仓行
- **WHEN** user 单击某行 (e.g. row for 600030.SH 中信证券)
- **THEN** HoldingsPanel emits `select-stock` with `{ stock_code, stock_name }`
- **AND** T0Trade onHoldingSelected handler MUST 更新 `selectedStockCode.value = stock_code`
- **AND** 传给 `<T0TaskCreateDialog :external-stock-code="selectedStockCode">`
- **AND** T0TaskCreateDialog watch MUST 写入 `form.stock_code` + 触发 `StockCodePicker` 联动显示 stock_name
- **AND** ElMessage.info MUST 弹出 "已选中 600030.SH"（250ms 节流避免与 dblclick 冲突）

### Scenario: 双击保持原 v53 apply-to-order 语义

- **GIVEN** HoldingsPanel 同时挂了 `@row-click` (v55 新) 和 `@row-dblclick` (v53 原有)
- **WHEN** user 双击某行
- **THEN** Trade.vue 父组件 MUST 仍收到 `apply-to-order` event（v53 REQ-FE-HOLDINGS-DBLCLICK 不破坏）
- **AND** 第 2 次 click MUST 跳过 emit（lastDblclickTs 节流 250ms 窗口）

### Scenario: 创建成功后主表新增 task 行

- **GIVEN** user 提交 T0TaskCreateDialog inline 表单
- **WHEN** store.createTask() 调用 /api/t0-tasks POST → 后端生成 `task.id` + 返回 task obj
- **THEN** 新 task MUST 自动出现在主表（t0TasksStore.tasks 已 push）
- **AND** NOT 重新 fetchPage（保持 store 单写入入口）
- **AND** Dialog MUST 自动关闭 (visible=false) + 提示成功

### Scenario: T0TaskDetail / T0TaskCreateDialog inline 共存

- **GIVEN** T0TaskCreateDialog 在 v55 commit.1 加了 `inline` prop
- **WHEN** inline=true
- **THEN** MUST 跳过外层 `<el-dialog>` 渲染，仅渲染 el-form 块（避免 el-dialog 嵌套导致 Teleport 错乱 + HoldingsPanel mounted hook 抛错）
- **AND** MUST emit `cancel` (新增) 而非 `submit` with null（语义清晰）
- **AND** T0Trade.vue MUST 监听 `@cancel="hideDialog"` + `@submit="onCreateSubmit"`

### Scenario: 删除 (Non-Goals)

下列功能**不**在 REQ-FE-230 范围内（新需求**不**回退）：
- v54 REQ-FE-220 的 lib/t0-calc.js 5 函数保留（`calcT0Pnl`/`calcExposure`/`calcInitialQuota`/`calcT0ReturnRate`/`resolveBalancePrice`）— 即使主表不再 holdings 视角仍可能被详情页/操作逻辑复用
- v54 主表 11 列（持仓视角）已永久删除
- v54 drawer T0TaskList 抽屉已永久删除
- v18 的 store.archiveTask 仍调用 api.remove (DELETE) 的历史 bug 不在本次范围（UI 标"归档"实际 DELETE，违和但不影响新增流程）
- HoldingsPanel `@row-dblclick` 保持 v53 apply-to-order 语义不变

### 风险与验收

| 风险 | 验收 |
|---|---|
| el-dialog 嵌套导致 Teleport 错乱 + HoldingsPanel mounted hook 抛错 | T0TaskCreateDialog 加 inline prop；父 dialog body 才用 inline=true |
| 单击与 dblclick 触发冲突（250ms 窗口） | HoldingsPanel 用 lastDblclickTs 节流：单击除非紧接 dblclick 才 emit select-stock |
| task.id 在前端 ID 类型可能是 number/string | 主表用 template 默认 toString() 转文本展示 |
| 任务创建后主表不刷新 | store 单写入（tasks.push + total +1），避免双写 |
| HoldingsPanel 单击后 StockCodePicker 不显示 stock_name | StockCodePicker 接收到 stock_code 后默认从 stocksStore 查名称 |

### 相关文件

- `client/src/views/T0Trade.vue`（v55 commit.3 主体改写 +511/-231 = 净 -180 行；hotfix 1 增 4 行）
- `client/src/components/trade/T0TaskCreateDialog.vue`（v55 commit.1 +1 prop +1 emit +watch；hotfix 2 +inline 模式 94/-30）
- `client/src/components/trade/HoldingsPanel.vue`（v55 commit.2 +select-stock emit +onRowClick；hotfix 3 节流修正 +6/-9）
- `client/src/stores/t0_tasks.js`（无改动，复用 createTask / activeTasks）
- `client/src/api/t0_tasks.js`（无改动）

---

## REQ-FE-231: T0 task 一键配平——前端计算差值 + 下市价单（v56 实施）

### 修改

新增需求。

### 新增 REQ

**系统 SHALL** 在 T0Trade 页面"快速做T"主表"配平"按钮按下时：

1. **差值计算（前端）**：从 `holdingsStore.orders.filter(o => o.task_id === task.id && status ∈ '已成交')` 拿出该 task 全部已成交订单，按方向求和
   - `buy_vol  = sum(order.volume for order in buy_orders)`
   - `sell_vol = sum(order.volume for order in sell_orders)`
   - `diff     = buy_vol - sell_vol`
2. **方向决定**：
   - `diff > 0` → 多买了，反向 = **SELL** (`order_type: '24'`)
   - `diff < 0` → 多卖了，反向 = **BUY** (`order_type: '23'`)
   - `diff === 0` → 已平衡，按钮 disabled
3. **下单**：复用 `useT0OrderSubmit.submitOrder`，参数：
   ```js
   {
     orderType: diff > 0 ? '24' : '23',  // 反向
     volume: Math.abs(diff),            // |diff|
     price: 0,                          // 市价
     taskId: task.id,
     priceType: 'market',               // priceTypeCode=44
     t0_coefficient: 1,                 // 默认配平系数
     user_def: 'T0-balance'             // 标签区别于普通 T0 委托
   }
   ```
4. **实时显示**：下半区委托表变化 → 实时更新差值 → 主表"配平"按钮文案刷新
5. **deletes**：原 `POST /api/t0-tasks/{id}/balance` 后端 endpoint + 前端 `t0TasksApi.balance` + `store.balanceTask` + `T0TaskDetail.onBalance` 全部删除

#### Scenario 1: 多买了，应反向卖
- **GIVEN** task 有 3 笔成交：买 100 / 买 200 / 卖 100 (已成交)
- **WHEN** 用户点"配平"按钮
- **THEN** 前端算 `diff = (100+200) - 100 = +200`，方向 = SELL，下市价卖 200 股

#### Scenario 2: 多卖了，应反向买
- **GIVEN** task 有 2 笔成交：卖 500 / 买 200 (已成交)
- **WHEN** 用户点"配平"按钮
- **THEN** 前端算 `diff = 200 - 500 = -300`，方向 = BUY，下市价买 300 股

#### Scenario 3: 已平衡，按钮 disabled
- **GIVEN** task 全部已成交订单买=卖 (e.g. 买 1000 / 卖 1000)
- **WHEN** 渲染主表
- **THEN** "配平"按钮 disabled，文案显示"已平衡"

#### Scenario 4: 实时刷新（推送）
- **GIVEN** task 当前 `diff = 0`，主表"配平"按钮 disabled
- **WHEN** 新一笔 `trd_cfm` 推送到达 → `holdings.applyTradePush` 写缓存
- **THEN** 自动触发 diff 重计算，按钮 enabled 并显示新的差值

#### Scenario 5: 后端 endpoint 404
- **GIVEN** 前端代码彻底删除 `balanceTask` / `balance()`
- **WHEN** 用户访问 T0Trade 不再发任何 `/balance` 请求
- **THEN** network tab 无 `POST /api/t0-tasks/{id}/balance` 调用记录

---

## REQ-FE-232: T0Trade 主页面上下分区布局（v56 实施）

### 修改

新增需求。

### 新增 REQ

**系统 SHALL** 把 T0Trade 主页布局改为上下两区：

1. **上半区**（flex 1）：现有 8 列 task 表
2. **下半区**（flex 1）：当前选中 task (`selectedTaskId`) 的实时委托表 —— 7 列（委托号/方向/价格/数量/状态/下单时间/备注）
3. **联动**：上半 task 表行选中（点击）或 el-select 选 task → 下半委托表自动 filter (`holdings.orders.filter(o => o.task_id === id)`)
4. **实时推送**：ws ord_cfm/trd_cfm 推送到达 → applyOrderPush/applyTradePush 守门 → orders ref 更新 → 下半表 Vue 自动响应
5. **空态**：未选中 task → 下半区显示"请先选中一个 T0 任务"

#### Scenario 1: 选中 task 后看到委托
- **GIVEN** 选中 `selectedTaskId=2`
- **WHEN** 渲染下半区
- **THEN** 显示 stock_code=task.stock_code 的所有委托（按 order_time desc 排序），7 列

#### Scenario 2: 新委托推送到达
- **GIVEN** 选中 task=2，下半区显示 2 笔委托
- **WHEN** 用户在 trade 面板下买单 100 股 @ 11 元，server 收 ord_cfm 推送
- **THEN** holdings.applyOrderPush 写缓存 → 下半表自动多一行

#### Scenario 3: 推送撤单/成交更新
- **GIVEN** 下半表显示有 1 笔已成交买单
- **WHEN** server 推 trd_cfm (status 51)
- **THEN** 下半表 status 列更新（51 → 绿色"已成交"），上半"配平"按钮实时算 diff 变化

### Why

- 用户明确："**去掉这个接口，一键配平按钮，计算委托方向数量后，调下单接口下市价单**"
- 现实：v18/v54 balance endpoint 实现的 净敞口配平 把"算"和"报"绑在一个 RPC，前端无实时性
- 重构后：推送即实时算，UI 即时反馈，UX 提升

### 相关文件

- `client/src/views/T0Trade.vue`（v56 layout +120/-39 = 净 +81 行；3 commit 拆分）
- `client/src/api/t0_tasks.js`（v56 commit.3 删 `balance()` 方法 +4 行）
- `client/src/stores/t0_tasks.js`（v56 commit.3 删 `balanceTask()` action +4 行）
- `client/src/components/trade/T0TaskDetail.vue`（v56 commit.3 删 `onBalance()` 函数 8 行）
- `client/src/components/trade/T0TaskList.vue`（v56 commit.3 删 `配平`按钮 +emit 注册 +2 行）
- `server/api/t0_tasks.py`（v56 commit.3 删 `/balance` endpoint -2 行）

---

## REQ-FE-233: T0Trade 主表 9 列布局 + 持仓/行情从 store 实时取 (v57 commit.1)

### 目标

T0Trade 主表 (上半区) 由 8 列扩展为 9 列, 列布局符合 v57 设计:
1. 状态 / 2. 任务编号 / 3. 标的 / 4. **期初持仓** (110→90) / 5. **当前持仓** (100→80) / 6. **最新价(涨跌幅)** (新增 130→140) / 7. 做T盈亏 / 8. 做T收益率% / 9. 操作 (240→280)

### 数据源 (实时匹配, 不存 task 表)

| 列 | 数据源 | 备注 |
|---|---|---|
| 期初持仓 | `holdingsStore.positions[code].last_vol` | holdings.py L22 # 期初 |
| 当前持仓 | `holdingsStore.positions[code].vol` | 当前持仓总数 |
| 最新价 | `quoteStore.getLastPrice(code)` | 实时推送 |
| 涨跌幅 | `quoteStore.getChangePct(code)` | 实时推送 |

### Task 表 base_volume / target_volume 字段

**保留** (保守做法): 服务端 `close_task` / `service.balance_task` 算法仍消费这两个字段; 前端主表**不展示**, 数据**全部从缓存匹配** (用户原话: "任务不需要关注这些")

### Scenario 1: 首屏加载数据延迟

- **GIVEN** 用户 reload 页面
- **WHEN** T0Trade.vue 渲染首屏
- **THEN** 列 4/5/6 初始显示 `0` (holdingsStore 异步加载)
- **AND** holdingsStore/quoteStore reactive 推送到位后 (≈1.5s) 列 4=last_vol / 列 5=vol / 列 6=last_price + change_pct

### Scenario 2: 列宽自适应

- **GIVEN** 9 列布局总宽 1160px > 容器 1010px
- **THEN** el-table 自动横滚 (CSS `overflow-x: auto`)
- **AND** 操作列 280px fixed right 浮于右侧

---

## REQ-FE-234: T0Trade 操作列 4 按钮 + 页顶做T配置 + 二次确认 dialog (v57 commit.2)

### 操作列按钮 (4 个)

| 按钮 | 颜色 | 行为 |
|---|---|---|
| 买 | success 绿 | 按 row.stock_code + 全局配置算 vol/price + (勾确认→弹 dialog / 不勾→立即下单) |
| 卖 | danger 红 | 同上, 方向=卖 |
| 配平 | warning 橙 | (v56 保留逻辑) 前端算 diff + 下市价单 |
| 归档 | info 灰 | (现有) 调 archiveTask action |

**删除**: 详情按钮 (用户原话 4 个按钮未列) + 平仓按钮 (用户原话 4 个按钮未列)

### 页顶配置 row (`t0-config-bar`)

4 select + 1 checkbox, 影响所有主表"买/卖"按钮:

| 控件 | 默认值 | 选项 |
|---|---|---|
| 百分比 | 25% | 25% / 50% / 75% / 100% |
| 价格 | 最新价 | 最新价 / 市价 |
| 数量基数 | 当前持仓 | 当前持仓 (vol) / 可用持仓 (avl_vol) / 期初持仓 (last_vol) |
| 二次确认 | off | on/off checkbox |

### vol 计算公式

```
volume = floor(positions[stock_code][qty_base_field] × pct)
```

price_type 选择:
- `latest` (最新价): placeOrder(price=last_price, price_type=11 限价)
- `market` (市价): placeOrder(price=0, price_type=44 市价)

### 二次确认 dialog

勾 checkbox 时, 按"买/卖"立刻弹 el-dialog 显示 5 行:
1. 标的 (stock_code)
2. 方向 (买/卖 colored tag)
3. 数量 (vol + hint "qtyBase × pct")
4. 价格 (¥x.xx 最新价 / "市价 (柜台撮合价)")
5. 关联 task (task #N)

底部 2 按钮: 取消 (不单) / 确认下单

### Scenario 1: 25% + 最新价下单

- **GIVEN** task #2 行, 持仓 vol=19,600, 最新价=10.77
- **WHEN** 按"买"按钮 (不勾确认)
- **THEN** 立即 placeOrder(volume=4900, price=10.77, price_type=11)
- **AND** toast "新委托: 000001.SZ 买 4900@10.77"

### Scenario 2: 二次确认弹 dialog

- **GIVEN** 勾二次确认 checkbox
- **WHEN** 按"买"按钮
- **THEN** 弹 dialog 显示: 标的=000001.SZ, 方向=买, 数量=4,900 股 (vol × 25%), 价格=¥10.77 (最新价), task=#2

### Scenario 3: 50% + 最新价

- **GIVEN** pct=50%, priceType=latest
- **WHEN** 按"买"按钮 (勾确认)
- **THEN** dialog 显示数量=9,800 股 (vol × 50%) + 价格=¥10.77

### Scenario 4: 25% + 市价

- **GIVEN** pct=25%, priceType=market
- **WHEN** 按"买"按钮 (勾确认)
- **THEN** dialog 显示数量=4,900 股 + 价格="市价 (柜台撮合价)"

### Scenario 5: dialog 取消不单

- **WHEN** dialog 内点"取消"
- **THEN** 不调 placeOrder, dialog 关闭, 无 toast

---

## REQ-FE-234 Why

- 用户原话: "操作栏按钮改为: 买入 卖出 配平 归档"; "增加下拉框选择百分比+价格+做T任务"; "勾选了点击下单的时候，会弹出来下单的标的、数量、价格和买入、卖出按钮，点击了才能下出去"
- v56 之前主表只有 编辑/归档, 缺 买/卖/配平 (要做T 必须从主表出发)
- 二次确认 dialog 防误触 (特别是按"卖"按钮时, 卖错损失大)

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
