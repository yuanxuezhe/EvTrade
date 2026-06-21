# frontend — Vue3 前端

> 📖 **DB schema**详见 [`data-model/spec.md`](../data-model/spec.md)（前端 store 与 DB schema 校对）

## Purpose

单页应用，12 个视图，WebSocket 实时更新，JWT 鉴权。
部署在 Windows dev 环境，监听 :50998。

## Requirements

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

- **`orderStore.fetchOrders()` / `orderStore.fetchOrders(stockCode)`** 已删除 — v8 委托由 ws `order_update` push 兜底
- **`orderStore.fetchTrades()` / `orderStore.fetchTrades(stockCode)`** 已删除 — v8 成交由 ws `trade_update` push 兜底
- **MUST**: 委托/成交加载走 `holdingsStore.bootstrap()` (App 启动) 或 `holdingsStore.refreshAll()` (手动刷新)
- 详见归档 `archive/2026-06-22-fix-v8-single-source-violations-r2/spec-deltas/frontend.md`

### REQ-FE-006: 委托 status 本地推断（前端镜像后端）

- **位置**：`client/src/utils/format.js` 导出 `inferOrderStatus(order, brokerStatus?)` 函数
- **契约**：与 `server/services/push_handlers.py:_infer_order_status` **逐行一致**（同规则、同终态集合、同输入输出）
- **调用点**：
  - `holdings.js:applyOrderPush` 收到 `order_update` 时，对每条 order 调一次重算（防御性）
  - `order.js:fetchOrders` 拉取完后批量重算
- **视图层契约**：
  - 状态码分组集合（`_PENDING_NUMERIC` / `_FILLED_NUMERIC` / `countByStatus`）必须用**本地推断码** 49/50/51/52/53/54/55/56
  - 不要再用 broker 原始码（55=部成/56=已成）的旧逻辑

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
