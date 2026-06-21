# push spec delta — status 字段语义契约

**合并到**：`openspec/specs/push/spec.md` REQ-PUSH-002 + REQ-PUSH-003

## REQ-PUSH-002 增量

ord_cfm 行的 status 字段语义：`order_update` 推的 status = DB Order.status = **后端本地推断结果**（不是 broker 原始码）。

## 新增 REQ-PUSH-005: status 字段语义（v6，本地推断）

- 后端 `handle_ord_cfm` / `handle_trd_cfm` 写入 Order.status 时，**统一调用 `_infer_order_status` 本地推断**，不直接抄 broker 推送的 status
- WS `order_update` 推送的 status 字段 = DB 中的 status 字段 = 本地推断结果
- **前端契约**：
  - 前端 `inferOrderStatus(order, brokerStatus?)` 必须与后端 `_infer_order_status` **逐行一致**（同函数同输入同输出）
  - 前端 store 收到 `order_update` 时，对每条 order 调一次前端 `inferOrderStatus` 重算（防御性，避免与后端实现分叉）
  - 视图层（Trade.vue / Orders.vue）的 status 分组集合必须用**后端本地推断码**：49/50/51/52/53/54/55/56（不是 broker 原始码 55/56 等）
- **后端函数位置**：`server/services/push_handlers.py:_infer_order_status`
- **前端函数位置**：`client/src/utils/format.js:inferOrderStatus`
