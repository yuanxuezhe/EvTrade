# Tasks: Frontend mirrors backend order status inference

- [ ] 1. `client/src/utils/format.js`: 新增 `inferOrderStatus(order, brokerStatus?)` 与 `TERMINAL_STATUSES`，与 `server/services/push_handlers.py:_infer_order_status` 逐行一致
- [ ] 2. `client/src/stores/holdings.js:applyOrderPush`: 收到推送时调前端 `inferOrderStatus` 重算 order.status
- [ ] 3. `client/src/stores/order.js:cancelOrder(orderNo, trdDate)`: 不再硬编码 `order.status = '54'`；撤单由 ord_cfm push 异步改
- [ ] 4. `client/src/views/Trade.vue`: `_PENDING_NUMERIC` / `_FILLED_NUMERIC` 改用本地推断码（49/50/51）
- [ ] 5. `client/src/views/Orders.vue:countByStatus`: 改用本地推断码分组（filled=51 等）
- [ ] 6. `client/src/utils/format.js`: 更新 `STATUS_LABEL` 注释（"本地推断码"取代"柜台数字"）
- [ ] 7. `pytest server/ -v` 全绿
- [ ] 8. 手动验证：下单 → 收 trd_cfm → 视图 status 与后端 DB 一致
- [ ] 9. 手动验证：撤单 → 收 ord_cfm(53) → 视图 status 显示"已撤"
- [ ] 10. 提交：`fix(frontend): status 推断与后端 _infer_order_status 对齐`
- [ ] 11. 归档：spec 已合并到 specs/ 后，`mv openspec/changes/2026-06-16-frontend-infer-order-status openspec/changes/archive/`
