# tasks — stock-target-cell-unify

## P0 — 组件骨架

- [x] 新建 `client/src/components/cells/StockTargetCell.vue`（props + 模板 + scoped style）

## P1 — 接入（业务文件）

- [x] HoldingsPanel.vue 替换 `#column-stock_code` → `<StockTargetCell>` + 加 import
- [x] TodayOrdersPanel.vue 替换 2 处 + 加 import
- [x] T0Trade.vue 替换 2 处 + 加 import + 删无用 stockName import
- [x] CachePositions.vue 替换 + 加 import + 删 stockName import
- [x] CacheOrders.vue 替换 + 加 import + 删 stockName import
- [x] CacheTrades.vue 替换 + 加 import + 删 stockName import
- [x] Dashboard.vue 替换 + 加 import + 删 stockName import
- [x] PositionTable.vue 替换 + 加 import
- [x] StkPool.vue 替换 detail cell + 加 import + 删 .detail-line .detail-code .detail-name CSS + 删 `getStockName` 函数
- [x] AdminStockConfig.vue 替换 + 加 import（`:show-name="false"`）
- [x] HistoryQuoteCompletion.vue 替换 + dialog `el-input` → `<StockCodePicker>` + 加 import + addRules 改 validator

## P2 — 清理

- [x] 7 处 scoped 块冗余 `.tp-stock-code {...}` CSS 删除（trade-panel.css 全局已定义）
- [x] StkPool `.detail-line / .detail-code / .detail-name` 3 个 CSS 类删除（替换后不再用）
- [x] utils/stockNames 5 个文件的 import 清理（HoldingsPanel 保留，业务回调还要用）
- [x] utils/tableColumns.js STOCK_CODE / STOCK_TARGET 注释模板同步到 StockTargetCell

## P3 — 验证

- [x] grep 残留 = 0（业务文件 `text-mono tp-stock-code`）
- [x] 双向 import 校验（用组件但没 import = ✗）9 文件全 ✓
- [x] `npm run build` 编译通过 30.92s
- [x] `pytest server/tests/services/quote_sync/` 10/10 passed

## P4 — 知识库

- [x] 知识库/前端/组件/通用组件.md 加入 `cells/StockTargetCell.vue` 行 + 核心实现段
- [x] 创建 openspec change (proposal.md + tasks.md + spec-deltas/前端组件.md)
