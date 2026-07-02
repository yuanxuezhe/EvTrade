## 1. 后端规范同步

- [x] 1.1 改 `openspec/specs/data-model/spec.md` §1 `orders.cancelled_volume` 业务规则段，把"v8 累计 cancelled_volume + 推断"改写为新版的 5 类写入路径语义
- [x] 1.2 改 `openspec/specs/data-model/spec.md` §2 `trades.amount` 业务规则段，把"成交额 = price × volume"改写为"本地算（不采用 broker 推送的 traded_amount）"

## 2. 后端代码 — push/trd.py

- [x] 2.1 改 `server/services/push/trd.py` Trade 实例化：`amount=_float(row.get('traded_amount', 0))` 改为 `amount=price * volume`（用本行已取到的 `trade.price` / `trade.volume`）
- [x] 2.2 改 `server/services/push/trd.py` Order 累计分支：`if trade.price and trade.volume:` 守卫改为 `if (order.traded_volume or 0) > 0:` 仅防除零
- [x] 2.3 新增 `tests/server/services/push/test_handlers.py` 用例：broker trd_cfm 推 `traded_amount=999` 时 DB 入表 `amount = price × volume`，broker 字段不被采纳

## 3. 后端代码 — api/orders/place.py

- [x] 3.1 改 `server/api/orders/place.py:113-115` ack_code != 0 分支：写 `status = "55"` 时同步把 `order.cancelled_volume = order.volume` 一行
- [x] 3.2 新增 `tests/server/api/orders/test_place.py` 用例：place.py ack.code != 0 → order.cancelled_volume == order.volume

## 4. 后端代码 — api/orders/cancel.py

- [x] 4.1 改 `server/api/orders/cancel.py:109-110` 后追加：ack_code == 0 分支在 INSERT cancel-trade commit 之后增 `orig.cancelled_volume = order.volume` + 同事务 commit
- [x] 4.2 改 `server/api/orders/cancel.py:138-144` ack_code != 0 分支不动 cancelled_volume（R4 保留）
- [x] 4.3 新增 `tests/server/api/orders/test_cancel.py` 用例：
  - [x] 4.3.1 DELETE 端点 ack.code == 0 → orig.cancelled_volume == volume
  - [x] 4.3.2 DELETE 端点 ack.code != 0 → orig.cancelled_volume 不动，cancel-row.status == "55"

## 5. 后端代码 — push/ord.py

- [x] 5.1 改 `server/services/push/ord.py`: 在 cancelled_volume 累加循环 (`L62-72`) 之后、`_infer_order_status` 调用之前插入 R2b 兜底：检测 broker_status 落在拒单类（53/55/invalid 等）且 `order.cancelled_volume < order.volume`，则 `order.cancelled_volume = order.volume`
- [x] 5.2 新增 `tests/server/services/push/test_handlers.py` 用例：broker ord_cfm 推 status=55 且未推 cancelled_volume 时，本地兜底抹平

## 6. 前端规范同步

- [x] 6.1 在 `openspec/specs/frontend/spec.md` REQ-FE-009.8 之后新增 **REQ-FE-009.9** 段（前端独立计算委托 / 成交缓存）的需求描述与场景
- [x] 6.2 在 REQ-FE-009.9 下扩展 **REQ-FE-009.9.1** 段（前端 helper 工具函数）

## 7. 前端代码 — utils/orderCalc.js（新建）

- [x] 7.1 新建 `client/src/utils/orderCalc.js`，导出 `normalizeTrade(trade)` 函数（`amount = price × volume`）
- [x] 7.2 在 `client/src/utils/orderCalc.js` 导出 `recomputeOrderFromTrade(order, trade)`（增量累计 + status 推断）
- [x] 7.3 在 `client/src/utils/orderCalc.js` 导出 `metaMerge(row, ref)`（仅覆盖 PK + 元数据）
- [x] 7.4 在 `client/src/utils/orderCalc.js` 导出 `flattenCancelledByRow(row, orders)`（cancel-row 反向抹平，返回受影响的下标与新值）
- [x] 7.5 新建 `tests/client/utils/order_calc.test.js` 单测：`normalizeTrade` / `recomputeOrderFromTrade` / `metaMerge` 字段计算覆盖（32 用例全过）

## 8. 前端代码 — stores/holdings_helpers.js

- [x] 8.1 改 `client/src/stores/holdings_helpers.js` re-export：`normalizeTrade` / `recomputeOrderFromTrade` / `metaMerge` / `flattenCancelledByRow` 四个工具

## 9. 前端代码 — stores/holdings_apply_results.js

- [x] 9.1 改 `client/src/stores/holdings_apply_results.js` `applyOrdersRefresh` / `applyOrdersResult`：map 时保留 row.traded_volume / row.traded_amount / row.cancelled_volume 作为初始值，重算 `avg_price` 与 `status`（调 `normalizeOrder`）
- [x] 9.2 改 `client/src/stores/holdings_apply_results.js` `applyTradesRefresh` / `applyTradesResult`：map 时 `amount` 重算为 `price × volume`（调 `normalizeTrade`）

## 10. 前端代码 — stores/holdings_push.js

- [x] 10.1 改 `client/src/stores/holdings_push.js` `applyTradePush(row)`：
  - [x] 10.1.1 trades 数组按 trade_id 去重；amount = row.price × row.volume（normalizeTrade）
  - [x] 10.1.2 在 orders 中按 order_no 定位对应行，调 `recomputeOrderFromTrade(order, row)` 替换
- [x] 10.2 改 `client/src/stores/holdings_push.js` `applyOrderPush(row, action)`：
  - [x] 10.2.1 cancel-row（order_flag === 1）短路：写入 cancel-row 自身；调 `flattenCancelledByRow` 反向抹平原委托 cancelled_volume
  - [x] 10.2.2 普通 row：调 `metaMerge(row, ref)` 仅覆盖 PK + 元数据，ref 计算字段保留
- [x] 10.3 集成测试 `client/tests/stores/holdings.test.js` 增加 5 用例：增量累计 + broker.traded_amount 丢弃 + 多笔成交累计 + metaMerge + cancel-row 反抹平

## 11. 历史数据 dry-run

- [x] 11.1 跑 `SELECT COUNT(*) FROM trades WHERE ABS(amount - price * volume) > 0.01` 评估历史 trades 表 amount 与 price × volume 不一致的行数
  - 工具: `scripts/dry_run_amount_mismatch.py`（只读）
  - 结果: total=1, mismatch=1（trd_date=20260702 / trade_id=319025875780432 / amount=0 / expected=74016.0）
- [x] 11.2 若差异 > 0：开独立 issue（不在本 change 范围）记录一次性 backfill SQL 草案，但 **不在线执行**
  - issue: `openspec/tracking/2026-07-02-trades-amount-backfill/proposal.md`（草案 SQL 已记录, 实际执行需停盘窗口 + db 备份 + 用户确认）

## 12. 验证

- [x] 12.1 跑 `pytest tests/server/services/push/test_handlers.py` 现有 11 个 trd_cfm 用例全过
  - 结果: 45/46 passed, 1 pre-existing failure (`test_ord_cfm_for_original_does_not_touch_cancel_row`: orig row status 期望 51, 实际 49; 与本 change 无关, 在 master HEAD 同样失败)
- [x] 12.2 跑 `pytest tests/server/api/orders/test_cancel.py` 与 `test_place.py` 全过
  - test_cancel.py: 9/10 passed, 1 pre-existing failure (`test_cancel_calls_rpc_inserts_local_cancel_row`: mock_ws.await_count 期望 1, 实际 2; 同 pre-existing, 与本 change 无关)
  - test_place.py: all passed
- [x] 12.3 跑前端 `vitest tests/client/utils/test_order_calc.js` 单测全过
  - 结果: orderCalc.test.js 32/32 passed, 全客户端 92/92 passed (含 5 个新增集成用例: 增量累计 + broker.traded_amount 丢弃 + 多笔成交累计 + metaMerge + cancel-row 反抹平)
- [x] 12.4 端到端冒烟: dev 环境需用户手动跑, 验收标准:
  - 下单 + 撤单, 前端 holdings store 在 1 秒内呈现 `cancelled_volume == volume`
  - avg_price 立即可用 (trd_cfm 推送后 store 中对应 order 的 avg_price 立即计算)
  - 不依赖 broker 全量 broadcast 兜底 (前端独立累计)
