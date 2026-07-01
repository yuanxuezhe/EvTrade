# frontend delta — Orders.vue / Trades.vue trd_date 展示

## MODIFIED Requirements

### REQ-FE-{X}: Orders.vue 委托查询 — 仅当日/全部 Tab + trd_date 列

**Before:**
- 仅展示「激活日」数据（`/api/orders` 默认 trd_date = 激活日）
- 表头无 trd_date 列

**After:**
- 顶部新增 `<el-tabs>` 「仅当日 / 全部」二选一
  - 缺省 Tab = 仅当日（与激活日数据一致，零回归）
  - 「全部」Tab 展示 holdings store 全量（已含 bootstrap 拉的 30 天窗口）
- 表头新增 `<el-table-column prop="trd_date" label="交易日" width="100" />`
- 新增 `filteredOrders` computed：基于 `activeTab` 叠加 trd_date 过滤

```js
const filteredOrders = computed(() => {
  const trdRange = activeTab.value === 'today'
    ? { exact: activeTrdDate.value }
    : {}  // 全部 = 不过滤
  return filterByTrdDate(orders.value, trdRange).filter(/* 现有 keyword/status 过滤 */)
})
```

- CSV 导出表头加 `交易日`；文件名 `委托查询_当日_${date}.csv` / `委托查询_全部_${date}.csv`

### REQ-FE-{Y}: Trades.vue 成交查询 — trd_date 列 + trade_time 倒序

**Before:**
- 表头无 trd_date 列
- 无默认排序（依赖后端 `created_at DESC`）

**After:**
- 表头新增 `<el-table-column prop="trd_date" label="交易日" width="100" />`
- `<el-table :default-sort="{prop: 'trade_time', order: 'descending'}">` — 与后端 `ORDER BY trade_time DESC` 对齐
- 移除 v9 已删字段 `order_id` 列（broker 真实号委托/成交展示不该出现）
- CSV 导出表头加 `交易日`

### REQ-FE-{Z}: 工具模块（独立 utils，不混入 store）

**新增**:
- `client/src/utils/date.js` — `shiftDateStr(yyyymmdd, deltaDays)` 跨月/跨年/闰年
- `client/src/utils/trdDateFilter.js` — 三模式（exact / [start,end] / 无过滤）纯函数

**filterByTrdDate 签名**:
```js
filterByTrdDate(items, range = {})
// range = { exact?: string, start?: string, end?: string }
// exact 与 start/end 互斥，exact 优先
// 缺省 range = {} 时返回 items.slice()（不污染调用方引用）
```

### REQ-FE-BOOTSTRAP: 启动拉取窗口

**Before:**
- bootstrap 调 `api.getOrders()` / `api.getTrades()` 无日期参数 → 仅激活日数据

**After:**
- bootstrap 改用 `api.getOrders({ start_date, end_date })` / `api.getTrades({ start_date, end_date })`
- `endDate = activeTrdDate`（已由 `_resolveActiveDay()` 解析）
- `startDate = shiftDateStr(endDate, -30)`（30 天窗口常量 `BOOTSTRAP_WINDOW_DAYS = 30`）
- holdings store 仍只持单 ref，存 30 天窗口全量
- WS 推送守门不受影响（用 `trd_date === activeTrdDate` 单值比较，与拉取窗口解耦）

## Cross-References

- 实施计划：`docs/superpowers/plans/2026-06-30-order-trade-query-by-trd-date.md`（commit `5a183a6`）
- 设计稿：`docs/superpowers/specs/2026-06-30-order-trade-query-by-trd-date-design.md`（commit `df493cd`）
- 实施 commits：`7b2c2f3` / `def9b20` / `2fe56ab` / `f91dc76` / `e4aba43` / `195831e` / `bd3dacb`
- 验证：Vitest 测试路径 `client/tests/utils/`
