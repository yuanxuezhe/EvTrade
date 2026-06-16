# Tasks: Schema refinement v7

## KB 步骤（已完成）

- [x] KB：`data-model/spec.md` §1 orders 表（删 client_order_id，加 user_def，删 2 个 UNIQUE）
- [x] KB：`data-model/spec.md` §2 trades 表（删 order_id，加 order_no 入 PK，重命名 index）
- [x] KB：`trading/spec.md` REQ-TRADE-002（v7 schema 调整说明）
- [x] KB：`push/spec.md`（v7 handle_trd_cfm 落库调整）
- [x] KB：建 `openspec/changes/2026-06-16-schema-refinement/{proposal,tasks}.md` + spec-deltas/

## 实施步骤

- [ ] 1. `server/models/orm.py` Order: 删 `client_order_id` 列 + 2 个 UniqueConstraint，加 `user_def` 列
- [ ] 2. `server/models/orm.py` Trade: 删 `order_id` 列 + `ix_trades_order` 索引，加 `order_no` PK 列 + `ix_trades_order_no` 索引
- [ ] 3. `server/api/orders.py:PlaceOrderRequest`: 删 `client_order_id` 字段，加 `user_def: str = ""`
- [ ] 4. `server/api/orders.py:OrderOut`: 删 `client_order_id`，加 `user_def`
- [ ] 5. `server/api/orders.py:place_order`: 幂等改用 `next_order_no(db)` 单调递增；不再 filter_by client_order_id
- [ ] 6. `server/services/push_handlers.py:handle_trd_cfm`: 落 Trade 时写 `order_no` 不写 `order_id`；order_no 缺失时打 warning + 跳过
- [ ] 7. `server/test_push_handlers.py`: 更新 Trade 构造（加 order_no，去 order_id）
- [ ] 8. `server/test_models.py`（如有）: Trade 字段调整回归
- [ ] 9. `server/test_orders_api.py`（如有）: PlaceOrderRequest 字段调整 + 幂等逻辑调整
- [ ] 10. `rm server/evtrade.db` 重置 DB
- [ ] 11. `pytest server/ -v` 全绿（除 2 个已知 Python 3.6 失败）
- [ ] 12. grep 自检：`client_order_id` / `Trade.order_id` 应只命中 archive/ 或本 spec
- [ ] 13. 提交 1：`refactor(orm): v7 schema — Order 去 client_order_id/uq_broker_id 加 user_def，Trade 去 order_id 加 order_no 入 PK`
- [ ] 14. 提交 2：`feat(api): place_order 幂等改用 order_no 单调递增 + user_def 透传`
- [ ] 15. 提交 3：`refactor(push): handle_trd_cfm 落 Trade 改用 order_no`
- [ ] 16. 提交 4：`test: schema v7 测试同步 + DB 重置`
- [ ] 17. 归档：spec 已合并后 `mv openspec/changes/2026-06-16-schema-refinement openspec/changes/archive/`
