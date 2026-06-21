# Frontend mirrors backend order status inference

## Why

`server/services/push_handlers.py:_infer_order_status` 在 v6（`order-pk-by-orderno`）已经把 `Order.status` 改为**本地推断**，不再直接抄 broker 推的 status。但前端完全没有跟着改：

- `client/src/stores/order.js:cancelOrder` 硬编码 `order.status = '54'`（broker 原始码，已废）
- `client/src/views/Trade.vue` 的 `_PENDING_NUMERIC` / `_FILLED_NUMERIC` 用了 broker 原始码：`_PENDING_NUMERIC = new Set(['48', '49', '50', '51', '52', '55'])`、`_FILLED_NUMERIC = new Set(['56'])` —— `55=部成` 是 broker 码，**后端本地推断 50=部成**。前端显示与后端 DB 错位
- `client/src/views/Orders.vue:countByStatus` 同问题：注释写"已成: 56, 部成: 55/52/53" —— 与本地推断"已成: 51, 部成: 50" 不一致
- `client/src/utils/format.js:STATUS_LABEL` 的语义注释（"后端已统一返回柜台数字；前端按数字翻译成汉字"）已经过期，v6 是本地推断码

**结果**：成交回报到达 WS 后，前端 `orders` store 用后端 DB 已推断的 `status` 字段（=50）写入，但视图层用 broker 码分组（55=部成），导致数据错位、用户看到的"状态不对"。

## What Changes

### 1. 新增前端推断函数

- 文件：`client/src/utils/format.js`
- 导出：`inferOrderStatus(order, brokerStatus?)`
- 实现：与 `server/services/push_handlers.py:_infer_order_status` **逐行一致**（同函数同输入同输出）
- 导出常量：`TERMINAL_STATUSES = ['51','52','53','54','55','56']`

### 2. 修 store / 视图层用本地推断码

- `client/src/stores/holdings.js:applyOrderPush` 收到推送时调前端 `inferOrderStatus` 重算（防御性）
- `client/src/stores/order.js`:
  - `cancelOrder(orderNo, trdDate)` 不再硬编码 `status = '54'`（撤单由 push 异步改 status）
  - 移除 `cancelOrder` 里的 status 覆盖逻辑
- `client/src/views/Trade.vue`:
  - `_PENDING_NUMERIC = new Set(['48','49','50'])`（仅待报/已报/部成 —— 用户视角"还可撤"）
  - `_FILLED_NUMERIC = new Set(['51'])`（已成终态）
  - 撤单/状态分组判断全部走 `STATUS_LABEL[order.status]` 显示
- `client/src/views/Orders.vue`:
  - `countByStatus` 用本地推断码：filled=51, partial=50/56, pending=48/49, cancelled=52/53/54, rejected=55

### 3. spec 同步

- `trading/spec.md` REQ-TRADE-002: 明确 `OrderOut.status` 语义为本地推断
- `push/spec.md` REQ-PUSH-005: 新增 status 字段语义契约 + 前端镜像要求
- `frontend/spec.md` REQ-FE-006: 新增 inferOrderStatus 工具要求

## Capabilities

### Modified Capabilities
- `trading`: status 语义契约
- `push`: status 推送契约
- `frontend`: 推断工具 + 视图层分组

## Impact

- `client/src/utils/format.js` — 新增 `inferOrderStatus` / `TERMINAL_STATUSES`
- `client/src/stores/holdings.js` — `applyOrderPush` 调推断
- `client/src/stores/order.js` — `cancelOrder` 不写 status
- `client/src/views/Trade.vue` — 状态码常量改
- `client/src/views/Orders.vue` — `countByStatus` 改
- 后端无改动

## Verification

1. `pytest server/` 全绿
2. 手动：登录 → 下单 → 收 trd_cfm → Trade.vue 今日委托表格的 status 字段与后端 DB 一致
3. 手动：撤单 → WS 收到 ord_cfm(status=52/53/54) → 前端 store 推断后 status 与后端一致
4. 浏览器：Trade.vue / Orders.vue / Position.vue 无 status 显示与 DB 不一致

## Spec Deltas

见 `spec-deltas/trading.md`、`spec-deltas/push.md`、`spec-deltas/frontend.md`。
