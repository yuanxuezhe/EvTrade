# trading spec delta — status 本地推断语义

**合并到**：`openspec/specs/trading/spec.md` REQ-TRADE-002

## 增量内容

`OrderOut.status` 字段语义（v6，本地推断）：
- 委托表 `status` 字段 = **后端本地推断的委托状态**（48/49/50/51/52/53/54/55/56）
- 推断函数：`_infer_order_status(order, broker_status=None)`（`server/services/push_handlers.py`）
- 规则：累计成交 + broker 推的撤单类信号 (52/53/54) 推断 49/50/51/53/56
- 终态 (51/52/53/54/55/56) 一旦写入不再被 trd_cfm 覆盖
- **前端必须镜像同一函数**：`client/src/utils/format.js` 提供 `inferOrderStatus(order, brokerStatus?)`，见 `frontend/spec.md` REQ-FE-006
- **前端不再信任 broker 推的 status 字段**（broker 状态码 vs 本地推断码不完全相同：例如 broker 55=部成 → 本地 50=部成）

## Known Issues 增量

- 🟥 ~~撤单 URL 用 order_id~~ → **v6 已改用 order_no**，但前端 Trade.vue 还在传 order_id（参见 change `2026-06-16-trade-page-show-order-no-and-cancel`）
- 🟡 前端 `order.js` `cancelOrder` 硬编码 `order.status = '54'`（与后端本地推断不一致）→ 参见 change `2026-06-16-frontend-infer-order-status`
- 🟡 前端 Trade.vue / Orders.vue 状态码分组用了 broker 原始码（55=已成等）而不是后端本地推断码（56=已成）→ 同上 change
