# frontend spec delta — 委托 status 本地推断（前端镜像后端）

**合并到**：`openspec/specs/frontend/spec.md`

## 新增 REQ-FE-006: 委托 status 本地推断（前端镜像后端）

- **位置**：`client/src/utils/format.js` 导出 `inferOrderStatus(order, brokerStatus?)` 函数
- **契约**：与 `server/services/push_handlers.py:_infer_order_status` **逐行一致**（同规则、同终态集合、同输入输出）
- **调用点**：
  - `holdings.js:applyOrderPush` 收到 `order_update` 时，对每条 order 调一次重算（防御性）
  - `order.js:fetchOrders` 拉取完后批量重算
- **视图层契约**：
  - 状态码分组集合（`_PENDING_NUMERIC` / `_FILLED_NUMERIC` / `countByStatus`）必须用**本地推断码** 49/50/51/52/53/54/55/56
  - 不要再用 broker 原始码（55=部成/56=已成）的旧逻辑
