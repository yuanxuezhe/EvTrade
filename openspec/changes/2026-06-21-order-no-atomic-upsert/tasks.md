# Tasks: order-no-atomic-upsert

## 立即执行

- [x] T1: 写 `proposal.md` + `tasks.md` + `spec-deltas/rpc-protocol.md`
- [ ] T2: 改 `server/services/order_no.py` 单语句 UPSERT + 函数内 commit + 改 docstring
- [ ] T3: 改 `server/api/orders.py:place_order` 适配
- [ ] T4: 增补 `server/test_order_no.py` 2 个新 case
- [ ] T5: 跑 `pytest server/test_order_no.py server/test_orders_api.py server/test_models.py` 全绿
- [ ] T6: 跑 `pytest server/test_reconcile.py` 验证对账
- [ ] T7: 合并 spec-delta 到 `openspec/specs/rpc-protocol/spec.md`
- [ ] T8: commit + push
- [ ] T9: 归档

## 验证矩阵（v7 纪律）

| 改动 | 必跑 | 备注 |
|---|---|---|
| `order_no.py` UPSERT | `test_order_no.py` | 核心 |
| `orders.py:place_order` 适配 | `test_orders_api.py` | 下游 |
| ORM 未改 | `test_models.py` | 回归 |
| 对账初始化时调用 | `test_reconcile.py` | 间接 |
| **不跑** | `test_auth.py` `test_ws_endpoint.py` 等 | 无关 |

## Out-of-scope

- 改 trading_day 序号生成
- 改 place_order 其他逻辑（三屏障、状态机）
- 改 add-config-validation / consolidate-rpc-parsers
- 真实环境部署 / QMT 柜台
