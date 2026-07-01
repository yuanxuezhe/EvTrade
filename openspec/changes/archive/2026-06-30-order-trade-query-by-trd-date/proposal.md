# 委托 / 成交按 trd_date 区间查询与展示

> 创建日期：2026-06-30
> 状态：applying → archived
> 范围：server 2 endpoint + client 2 view + 2 utils + bootstrap

## Why

`Orders.vue` / `Trades.vue` 当前通过 `holdings` store 缓存展示数据，几个缺口：

1. **当日委托语义不明**：仅展示「激活日」数据，无明确「只看当天下的单」切换
2. **缺无日期过滤入口**：`/api/orders/history` 必须显式传 trd_date 才能跨日查
3. **成交排序错位**：`/api/trades` 走 `ORDER BY created_at DESC`（DB 入库时间），与 broker 成交时刻有毫秒级漂移
4. **前端表格缺 trd_date 列**：表头没 element-plus `prop="trd_date"`，跨日数据无法直观分辨

## What

### 后端（API 入参，非 DB schema 变更）

- `GET /api/orders?start_date=YYYYMMDD&end_date=YYYYMMDD` 新增两个 query 入参（缺省=激活日，向后兼容）
- `GET /api/trades?start_date=YYYYMMDD&end_date=YYYYMMDD` 同上 + 排序改 `ORDER BY trade_time DESC, trade_id DESC`
- 过滤谓词 `start_date <= trd_date <= end_date`（trd_date 是已存在 DB 列）

### 前端

- 新增 `client/src/utils/trdDateFilter.js`（区间/exact/无过滤 三模式纯函数）
- 新增 `client/src/utils/date.js`（`shiftDateStr(yyyymmdd, deltaDays)` 跨月/跨年/闰年）
- `client/src/stores/holdings_bootstrap.js` 改 bootstrap 拉 `[activeDate-29, activeDate]` 30 天窗口
- `client/src/api/index.js` 改 `getOrders` / `getTrades` 接受 `{ startDate, endDate }` opts 对象
- `client/src/views/Orders.vue` 加 `<el-tabs>` 「仅当日 / 全部」+ trd_date 列 + `filteredOrders` computed
- `client/src/views/Trades.vue` 加 trd_date 列 + `default-sort: trade_time desc`

### 严格不动

- `Order` / `Trade` 表的 DB schema（不新增列、不改类型、不改索引）
- `POST /api/orders/place`、`DELETE /api/orders/{order_no}`、`/api/orders/history` 端点
- `OrderOut` / `TradeOut` schema 字段

## 实施

详细 9-task 实施步骤见 `tasks.md`。
设计稿见 `docs/superpowers/specs/2026-06-30-order-trade-query-by-trd-date-design.md`（commit `df493cd`）。
实施计划见 `docs/superpowers/plans/2026-06-30-order-trade-query-by-trd-date.md`（commit `5a183a6`）。

## 实施落地 commits

| 序 | commit | 说明 |
|---|---|---|
| 1 | `7006af2` | feat(server): orders query 新增 query 入参 start_date/end_date |
| 2 | `751cfc7` | docs: 明确 spec/plan 中 API 入参与 DB 列的术语区分 |
| 3 | `1e75a13` | docs: spec 中 Query 校验参数 pattern= 改为 regex= (Pydantic v1) |
| 4 | `fa15e88` | feat(server): trades query 新增 query 入参 start_date/end_date + 排序改 trade_time |
| 5 | `7b2c2f3` | feat(client): 新增 shiftDateStr 日期字符串工具 |
| 6 | `def9b20` | feat(client): 新增 filterByTrdDate 区间筛选工具 |
| 7 | `2fe56ab` | refactor(client): getOrders/getTrades 接受 options 对象 + 区间参数 |
| 8 | `f91dc76` | feat(client): bootstrap 拉 30 天窗口全量缓存 |
| 9 | `e4aba43` | feat(client): Orders.vue 加 仅当日/全部 Tab + trd_date 列 |
| 10 | `195831e` | feat(client): Trades.vue 加 trd_date 列 + 默认按 trade_time 倒序 |
| 11 | `bd3dacb` | fix(client): Trades.vue 移除 v9 已删字段 order_id 列 |
| 12 | `7c0430a` | docs: plan 中 vitest 测试路径改为 client/tests/ |

## 验证

- pytest `server/test_trades_api.py` 区间 + 排序用例绿（schema-refinement 那次跑过）
- 前端 `filterByTrdDate` / `shiftDateStr` 单元测试路径已在 `client/tests/`
- 手工：登录 → Orders.vue 切「全部」看到 30 天历史、Trades.vue 倒序

## 风险

- bootstrap 30 天窗口首屏慢：单账户量级可控（< 200ms）
- trade_time 同秒多条成交：二级 `trade_id DESC` 兜底

回滚：git revert 上述 12 commit 即可。
