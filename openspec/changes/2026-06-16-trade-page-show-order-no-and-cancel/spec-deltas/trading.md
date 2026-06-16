# trading spec delta — 撤单 API 契约

**合并到**：`openspec/specs/trading/spec.md` REQ-TRADE-003

## REQ-TRADE-003 增量

- `DELETE /api/orders/{order_no}?trd_date=YYYYMMDD`
- **v6 BREAKING**：URL 参数从 `order_id` 改为 `order_no`（本地 8 位序号）；后端按 `(trd_date, order_no)` 定位 Order
- 内部用查到的 `order.order_id` 调 `rpc.cancel_ord`；`order_id` 尚未到达时返 `409 BROKER_NOT_READY`
- 走 `cancel_ord` RPC，**不本地改 status**（由 ord_cfm push 异步回写）
- **前端约定**：Trade.vue 撤单按钮 → `orderStore.cancelOrder(orderNo, trdDate)` → `api.cancelOrder(orderNo, trdDate)` → `DELETE /api/orders/${orderNo}?trd_date=${trdDate}`
- **实现约定**：`api/orders.py` 中 import 使用别名 `from rpc.client import cancel_order as rpc_cancel_order`，避免与路由函数同名递归
