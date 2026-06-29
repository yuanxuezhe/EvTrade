# frontend — Vue3 前端

> 📖 **DB schema**详见 [`data-model/spec.md`](../data-model/spec.md)（前端 store 与 DB schema 校对）
> 📖 **接口契约**详见 [`../../../docs/server-rest-api.md`](../../../docs/server-rest-api.md)（FastAPI 端点 + 出入参）

## Purpose

单页应用，12 个视图，WebSocket 实时更新，JWT 鉴权。
部署在 Windows dev 环境，监听 :50998。

## Requirements

### REQ-FE-100: 业务数据 IndexedDB 持久化

The system SHALL persist 4 business data tables to IndexedDB to enable instant restore on page refresh:
- 资金 (asset)
- 持仓 (positions)
- 委托 (orders)
- 成交 (trades)

#### Scenario: 启动恢复

- **WHEN** user opens the app and is authenticated
- **THEN** `main.js` triggers `rehydrateFromIDB()` BEFORE `app.mount()`, which:
  1) opens `evtrade-cache` IDB
  2) checks `_meta.schema_version` — if mismatch, deletes and recreates the database
  3) reads 4 object stores in parallel (`asset` / `positions` / `orders` / `trades`)
  4) writes data back to corresponding Pinia stores
  5) rehydrate failures degrade silently (Pinia uses initial empty values)

#### Scenario: API 写透 (write-through)

- **WHEN** `fetchAsset()` / `fetchPositions()` completes successfully
- **THEN** the fetched data is written to IDB via `bulkReplace(storeName, items)` after Pinia state updates

#### Scenario: WS 推送增量写

- **WHEN** ws push handler (e.g. `applyOrderPush`) merges a row into Pinia state
- **THEN** the merged row is upserted to IDB by primary key (stock_code / order_no / [trd_date, trade_id]) via `putItem()`
- `applyQuote` does NOT persist (quote is real-time, not cached)

#### Scenario: Schema 升级 (全量清空)

- **WHEN** `SCHEMA_VERSION` constant in `idbStore.js` is incremented
- **THEN** on next DB open, `_meta.schema_version` mismatch triggers `deleteDB('evtrade-cache')` and recreates all 5 object stores fresh; user sees empty tables until next API call refills

#### Scenario: 不持久化的 store

- **WHEN** considering other Pinia stores
- **THEN** `auth` / `ui` / `ws*` / `quote` are NOT persisted (auth already handled by JWT, others are runtime state)

#### Scenario: DevTools 浏览

- **WHEN** developer wants to inspect cached data
- **THEN** open Chrome DevTools → Application → IndexedDB → `evtrade-cache` → 5 object stores visible (asset / positions / orders / trades / _meta)



### REQ-FE-001: 路由

| 路径 | 视图 | 鉴权 |
|---|---|---|
| `/login` | Login.vue | public |
| `/` | Dashboard.vue | login |
| `/trade` | Trade.vue | trader |
| `/orders` | Orders.vue | login |
| `/trades` | Trades.vue | login |
| `/positions` | → redirect `/to-management` | login |
| `/to-management` | Position.vue（快速做T） | login |
| `/t-strategy` | TStrategy.vue（策略做T） | login |
| `/algo-strategy` | AlgoStrategy.vue | login |
| `/holdings` | Holdings.vue | login |
| `/asset` | Asset.vue | login |
| `/users` | Users.vue | admin |
| `/profile` | Profile.vue | login |

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
#### REQ-FE-009.5: 撤单审计行（cancel-row）短路（v9）

- `holdings.applyOrderPush(row, action)`: 见 `row.order_flag === 1` 时**直接 merge + return**，**不**走 `_recomputeStatus`
  - 原因：cancel-row `volume=0, traded_volume=0`，`_recomputeStatus` 推算结果会是 `49`（已报），污染显示
  - cancel-row 的 `status` 由 DELETE 端点全权管理（53 已撤 / 55 废单），前端只 merge 不重算
  - 日志用「撤单审计」前缀区分正常推送
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
- **依赖注入模式**：helper 工厂通过参数接收 state ref + store getter（如 `getQuoteStore: () => useQuoteStore()`），避免循环依赖
- 详见归档 `archive/2026-06-24-phase-2-architecture-split/spec-deltas/frontend.md`

### REQ-FE-006: 委托 status 本地推断（前端镜像后端）

- **位置**：`client/src/utils/format.js` 导出 `inferOrderStatus(order, brokerStatus?)` 函数
- **契约**：与 `server/services/push_handlers.py:_infer_order_status` **逐行一致**（同规则、同终态集合、同输入输出）
- **v8 修订**：入参 `order` 增加 `cancelled_volume` 字段；推断规则以 `cancelled_volume` 主轴（详见 `push/spec.md` REQ-PUSH-005 v8 修订部分）
- **调用点**（v8 修订）：
  - `holdings.js:bootstrap` 拉取 `/api/orders` 后批量重算
  - `holdings.js:refresh` 拉取 `/api/orders` 后批量重算
  - `holdings.js:applyOrderPush` 收到 `order_update` 时重算
  - 统一通过 `holdings.js:_recomputeStatus(row)` helper 实现（不传 brokerStatus，按 cancelled_volume + traded_volume / volume 推断）
- **视图层契约**：
  - 状态码分组集合（`_PENDING_NUMERIC` / `_FILLED_NUMERIC` / `countByStatus`）必须用**本地推断码** 49/50/51/52/53/54/55/56
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

## Scenarios

### S-FE-001: 未登录访问 `/orders`

When 浏览器请求 `/orders`  
Then router.beforeEach 检测到无 token → 重定向 `/login?redirect=/orders`  
And 登录成功后跳回 `/orders`

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
  - 限价单（`price_type === PriceType.LIMIT`）委托价格输入支持 2 位小数（A 股最小变动单位 0.01 元）

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

## Known Issues (from analysis)

- 🟡 `TStrategy.vue` / `AlgoStrategy.vue` 各 43 行，**未实现内容**
- 🟡 `auth.js` store 应该在 401 时自动清 token + 跳 login，目前**依赖** axios 拦截器调用 `setUnauthorizedHandler`
- 🟥 ~~Trade.vue 撤单按钮传 `order_id`~~ → **本轮已修**（change `2026-06-16-trade-page-show-order-no-and-cancel`，改传 order_no + trd_date）
- 🟥 ~~Trade.vue / Orders.vue 用 broker 原始 status 码分组~~ → **本轮已修**（change `2026-06-16-frontend-infer-order-status`，改本地推断码 + 镜像推断）
- 🟥 ~~Trade.vue 今日委托表无 order_no 列~~ → **本轮已修**（同上 change）
- 🟢 UI 偏好已沉淀到 user memory，UI 改动前先查
- 🟢 ~~前端 5s 轮询 fetchOrders + 缓存双源（orderStore/holdings）~~ → **v8 已修**（change `2026-06-21-order-push-trd-date-authority`，统一 holdings 单一源 + 删 5s 轮询改手动刷新）
- 🟢 ~~T0Trade.vue submitOrder 误读 res.code 永远走 else 分支~~ → **v8 已修**（同上 change，submitOrder 改 orderStore.placeOrder）
- 🟢 ~~ws.test.js / useT0Balance.test.js 10 个预存失败~~ → **未修**（独立 issue，与 v8 改造无关）
