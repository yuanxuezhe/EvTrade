# Tasks: Trade.vue show order_no + cancel by order_no + trd_date

- [ ] 1. `client/src/api/index.js:cancelOrder(orderNo, trdDate)`: 签名改；DELETE /api/orders/${orderNo}?trd_date=${trdDate}
- [ ] 2. `client/src/stores/order.js:cancelOrder(orderNo, trdDate)`: 签名改；移除硬编码 `order.status = '54'`
- [ ] 3. `client/src/views/Trade.vue`: 表格加 `order_no` 列（股票后、方向前）
- [ ] 4. `client/src/views/Trade.vue`: 撤单按钮 `@click="handleCancel(row.order_no, row.trd_date)"`
- [ ] 5. `client/src/views/Trade.vue:handleCancel(orderNo, trdDate)`: 处理 `BROKER_NOT_READY` 友好提示
- [ ] 6. `client/src/views/Orders.vue`: 表格加 `order_no` 列
- [ ] 7. 全项目 grep `cancelOrder` 确认无遗漏调用方
- [ ] 8. `pytest server/ -v` 全绿
- [ ] 9. 手动验证：Trade.vue 表格显示 order_no + 撤单能成
- [ ] 10. 提交：`fix(frontend): 委托表格显示 order_no + 撤单用 order_no + trd_date`
- [ ] 11. 归档：spec 已合并后 `mv openspec/changes/2026-06-16-trade-page-show-order-no-and-cancel openspec/changes/archive/`
