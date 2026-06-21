# spec-deltas/frontend

## 改动

`openspec/specs/frontend/spec.md` 新增章节 `### REQ-FE-005: 委托/成交单一缓存源（v8）`：

### 权威缓存

- **唯一权威**：`client/src/stores/holdings.js` 持有 `orders / trades / positions / asset`
- `client/src/stores/order.js` 重写为**纯 actions**（不持有 orders/trades）：
  - `placeOrder` → RPC 调用 → 拦截器解包 → 拿到 `OrderOut` → `_upsertToHoldings(list[0])` 立即 unshift 到 holdings.orders
  - `cancelOrder` → 委托 `holdings.applyOrderPush(...)` 写一条 status=53 占位（broker ord_cfm 真正到达时再覆盖）
  - **不暴露** `orders / trades` getter，强制 view 显式 `useHoldingsStore().orders`
- 修复 `createOrder` 旧 bug：原版 `_handlePushFromOrder` 把 push 数组 push 进 orders 数组（类型错乱）

### 推送守门单点

- `client/src/stores/ws.js` 的 `_onOrderCfm` / `_onTradeCfm` **只调** `holdings.applyOrderPush/applyTradePush`：
  - 删 `useOrderStore` 引用
  - 匹配键 `order_no`，兜底 `row.remark`
  - 守门: 校验 `(activeTrdDate, order_no)`，非激活日忽略
- WS 不再双写 orderStore + holdings

### 视图层约束

- `client/src/views/Trade.vue`：
  - 删 `onMounted(fetchOrders)` 与 `setInterval(fetchOrders, 5000)` 轮询
  - 改用 `holdings.refreshAll` 手动刷新按钮（兜底）
  - 读 `holdings.orders / holdings.trades`，不读 `orderStore.orders`
- `client/src/views/T0Trade.vue`：
  - `submitOrder` 改走 `orderStore.placeOrder`（自动 upsert holdings）
  - 旧 `res.code` 检查改为 `res`（拦截器解包后是 OrderOut 对象，没有 code 字段）
  - 旧 bug：`res.code === 0` 实际永远走 else 分支

## 影响范围

### 前端 (5 文件)
- `client/src/api/index.js` (+getActiveDay + 注释)
- `client/src/stores/holdings.js` (activeTrdDate + bootstrap + 推送守门)
- `client/src/stores/order.js` (重写为单一 actions)
- `client/src/stores/ws.js` (单点入口，删 useOrderStore)
- `client/src/views/Trade.vue` (删轮询，改手动刷新)
- `client/src/views/T0Trade.vue` (submitOrder 改 orderStore.placeOrder)

## 测试

- `client/tests/stores/holdings.test.js` (待补，覆盖推送守门 + bootstrap 降级)
- `client/tests/stores/order.test.js` (待补，覆盖 placeOrder → _upsertToHoldings)

## 验证

- 端到端：下单 → orderStore.placeOrder → 立即 unshift holdings.orders → broker ord_cfm → push 注入 trd_date → ws.js → holdings.applyOrderPush(update) → 视图实时反映
- 切换交易日：重启 backend → push 注入新 activeTrdDate → 老 trd_date 推送被守门忽略
- 降级：getActiveDay 失败 → activeTrdDate=null → applyXxx 放行（log warn，不崩）

## BREAKING

- `orderStore.orders / orderStore.trades` getter **移除** —— 破坏性但只影响 Trade.vue / T0Trade.vue（已同步改）
- Trade.vue 删 5s 轮询 —— 改手动刷新按钮（`holdings.refreshAll`）
