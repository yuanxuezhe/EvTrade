# spec-deltas/trading

## 改动

`openspec/specs/trading/spec.md` 新增章节 `### REQ-TRADE-007: 响应统一性 + list 字段（v8）`：

- `POST /api/orders/place` 响应模型从 `{code, msg, order: OrderOut}` 扩展为 `{code, msg, order: OrderOut, list: List[OrderOut]}`
- **list 字段是冗余 1 行**（与 GET /api/orders 风格统一），前端 axios 拦截器 `_isRpcResponse` 自动解包后 `res.data` 是 1 元素数组
- 旧 `order` 字段保留（**v8 向后兼容**，不破既有 `r.json()["order"]["order_no"]` 风格调用）
- 柜台 RPC 失败时 `list` 也要返（不报错）
- 实施位置：`server/api/orders.py::PlaceOrderResponse` + `_to_order_out` helper + 3 个 return 填 list

## 影响范围

仅 `server/api/orders.py`：
- 新增 `_to_order_out(order)` helper（消除 3 处 OrderOut 重复构造）
- `PlaceOrderResponse` 加 `list: List[OrderOut] = []` 字段
- POST /place 的 3 个 return 路径都填 list
- POST /place WS broadcast payload 加 `trd_date + order_no + remark`（供前端推送守门）

无 model / DB / 鉴权改动。
