# Tasks — 委托/成交按 trd_date 区间查询与展示

## 后端

- [x] 1. `server/api/orders/query.py:list_orders` 新增 query 入参 `start_date` / `end_date`（commit `7006af2`）
- [x] 2. `server/api/trades.py:list_trades` 新增 query 入参 + 排序改 `trade_time DESC, trade_id DESC`（commit `fa15e88`）
- [x] 3. `server/test_trades_api.py` 区间 + 排序测试（commit `fa15e88` 同 commit 包含）
- [x] 4. docs: API 入参 vs DB 列术语明确（commit `751cfc7`）
- [x] 5. docs: Pydantic v1 校验用 `regex=` 不是 `pattern=`（commit `1e75a13`）

## 前端 utils

- [x] 6. 新增 `client/src/utils/date.js`（`shiftDateStr` 工具，commit `7b2c2f3`）
- [x] 7. 新增 `client/src/utils/trdDateFilter.js`（区间/exact/无过滤 三模式，commit `def9b20`）

## 前端 api + store

- [x] 8. `client/src/api/index.js` 改 `getOrders` / `getTrades` 接受 `{ startDate, endDate }` opts（commit `2fe56ab`）
- [x] 9. `client/src/stores/holdings_bootstrap.js` 改 bootstrap 拉 30 天窗口（commit `f91dc76`）

## 前端 view

- [x] 10. `client/src/views/Orders.vue` 加 `<el-tabs>` 仅当日/全部 + trd_date 列 + `filteredOrders` computed（commit `e4aba43`）
- [x] 11. `client/src/views/Trades.vue` 加 trd_date 列 + `default-sort: trade_time desc`（commit `195831e`）
- [x] 12. `client/src/views/Trades.vue` 移除 v9 已删字段 `order_id` 列（commit `bd3dacb`）

## 文档

- [x] 13. 设计稿 `docs/superpowers/specs/2026-06-30-order-trade-query-by-trd-date-design.md`（commit `df493cd`）
- [x] 14. 实施计划 `docs/superpowers/plans/2026-06-30-order-trade-query-by-trd-date.md`（commit `5a183a6`）
- [x] 15. plan 中 vitest 测试路径 `client/tests/` 修正（commit `7c0430a`）
- [x] 16. openspec change 补建（`openspec/changes/2026-06-30-order-trade-query-by-trd-date/`）

## 归档

- [x] 17. spec-deltas 合并到 `openspec/specs/{trading,frontend}/spec.md` 后 `mv → archive/`
