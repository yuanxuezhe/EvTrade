# Tasks — order-cancelled-volume

- [x] T1: `server/models/orm.py` Order 加 `cancelled_volume` 字段（commit `640419a`）
- [x] T2: `server/services/push_handlers.py` 累加 cancelled_volume + 改 `_infer_order_status`（commit `640419a`）
- [x] T3: `server/api/orders.py` OrderOut 加 `cancelled_volume` + `_to_order_out` 透传（commit `640419a`）
- [x] T4: DB 迁移脚本（`migrations/migrate_cancelled_volume.py`，commit `640419a`）
- [x] T5: `client/src/utils/format.js` inferOrderStatus 加 cancelled_volume 推断（commit `640419a`）
- [x] T6: `client/src/stores/holdings_helpers.js` `recomputeStatus` 透传 cancelled_volume（commit `bcf5811` 重构）
- [x] T7: `client/src/views/Trade.vue` 加"已撤"列（commit `640419a`）
- [x] T8: 更新 `openspec/specs/data-model/spec.md` orders 表（REQ-ORD-007）
- [x] T9: 更新 `openspec/specs/push/spec.md` REQ-PUSH-005
- [x] T10: 更新 `openspec/specs/frontend/spec.md` REQ-FE-006
- [x] T11: 更新 `openspec/specs/trading/spec.md` REQ-TRADE-002
- [x] T12: 跑测试 + 浏览器验证
- [x] T13: commit
