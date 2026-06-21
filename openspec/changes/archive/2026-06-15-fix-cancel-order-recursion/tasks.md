# Tasks — fix-cancel-order-recursion

## 实施步骤

- [ ] 1. 确认问题：读 `server/api/orders.py` 确认 import 被路由函数覆盖
- [ ] 2. 改 line 32：`from rpc.client import ord_stk, cancel_order as rpc_cancel_order, qry_orders`
- [ ] 3. 改 line 269：`ack = await rpc_cancel_order(order_id=order_id)`
- [ ] 4. 写单测 `server/test_orders_api.py::test_cancel_order_calls_rpc`
  - mock `rpc_cancel_order` 返回 `{code: 0, msg: "", list: []}`
  - 调用 DELETE → 断言 mock 被调用且非递归
- [ ] 5. `pytest server/test_orders_api.py` 全绿
- [ ] 6. commit: `fix(api): cancel_order 递归调用改为 RPC 调用`
- [ ] 7. 更新 `trading/spec.md` 补充 import 约定

## 验证

- [ ] `pytest server/` 全绿
- [ ] 手动：DELETE /api/orders/{id} 返回撤单 ack 而非 RecursionError
- [ ] `git log --oneline -1` 显示新 commit
