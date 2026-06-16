# Trade.vue: show order_no + cancel by order_no + trd_date

## Why

后端在 v6（`order-pk-by-orderno`）已经把撤单路由改为 `DELETE /api/orders/{order_no}?trd_date=YYYYMMDD`，并明文要求"按 `(trd_date, order_no)` 定位"。

但前端 `client/src/views/Trade.vue:82` 撤单按钮还传 `row.order_id`：
```vue
@click="handleCancel(row.order_id)"
```
和 `client/src/api/index.js:142` 调 `DELETE /api/orders/${orderId}`（无 trd_date query），调后端必然 404（后端按 order_no 查不到 broker order_id）。

同时 `Trade.vue`「今日委托」表 12 列里**没有 `order_no` 列**——用户看不到本地 8 位序号，无法对账/排查。

`Orders.vue`（委托查询）也只有 `order_id` 列没有 `order_no` 列。

## What Changes

### 1. Trade.vue 表格加 `order_no` 列

- 位置：股票列后、方向列前
- 显示：`<span class="text-mono text-secondary">{{ row.order_no }}</span>`
- 宽度：100
- 复制：`show-overflow-tooltip`

### 2. Trade.vue 撤单改 order_no + trd_date

- 改：`<el-button @click="handleCancel(row.order_no, row.trd_date)">`
- `handleCancel(orderNo, trdDate)`:
  - 调 `orderStore.cancelOrder(orderNo, trdDate)`（不再是 `cancelOrder(orderId)`）
  - 错误处理：捕获 `BROKER_NOT_READY` 弹 ElMessage.warning

### 3. orderStore / api 改签名

- `client/src/stores/order.js:cancelOrder(orderNo, trdDate)`:
  - 调 `api.cancelOrder(orderNo, trdDate)`
  - **不再硬编码** `order.status = '54'`（由 ord_cfm push 异步改）
- `client/src/api/index.js:cancelOrder(orderNo, trdDate)`:
  - 调 `DELETE /api/orders/${orderNo}?trd_date=${trdDate}`
  - `trdDate` 必传

### 4. Orders.vue 表格加 `order_no` 列

- 位置：股票代码后
- 调 `cancelOrder(row.order_no, row.trd_date)`

### 5. spec 同步

- `trading/spec.md` REQ-TRADE-003 明确前端撤单契约
- `frontend/spec.md` REQ-FE-007 / REQ-FE-008 新增

## Capabilities

### Modified Capabilities
- `trading`: 撤单 API 契约
- `frontend`: 撤单 + 显示

## Impact

- `client/src/views/Trade.vue` — 加列 + 改撤单
- `client/src/views/Orders.vue` — 加列
- `client/src/stores/order.js` — `cancelOrder` 改签名
- `client/src/api/index.js` — `cancelOrder` 改签名
- 后端无改动（已就位）

## Verification

1. `pytest server/` 全绿
2. 手动：登录 → Trade.vue → 找一笔"已报"委托 → 点撤单 → 后端 `server.log` 出现 `DELETE /api/orders/{order_no}?trd_date=...` 200
3. 手动：Trade.vue 表格能看到 8 位 `order_no`
4. 手动：撤单后 ord_cfm 推送到达 → 表格 status 实时变"已撤"
5. 边界：broker order_id 尚未到达时撤单 → 弹"BROKER_NOT_READY"友好提示

## BREAKING

- `api.cancelOrder(orderId)` → `api.cancelOrder(orderNo, trdDate)` — 调用方全改
- `orderStore.cancelOrder(orderId)` → `orderStore.cancelOrder(orderNo, trdDate)`
- 全项目无其他调用方（已 grep 验证：`grep -r "cancelOrder" client/src/`）

## Spec Deltas

见 `spec-deltas/trading.md`、`spec-deltas/frontend.md`。
