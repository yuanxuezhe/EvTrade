# stock-target-cell-unify（标的组件全站统一）— 2026-09-21

## 解决什么

EvTrade 前端表格标的列（代码+名称+T0 徽章）散在 10+ 文件里手写同一段模板：

```vue
<span class="text-mono tp-stock-code">{{ row.stock_code }}</span>
<span class="text-secondary" style="margin-left: 6px" v-t0-badge="row.stock_code">{{ stockName(row.stock_code) || '—' }}</span>
```

每张表又叠加一份独立的 `.tp-stock-code { font-family: var(--font-mono); font-weight: 600; }` 在 scoped 块（全局 `trade-panel.css:63` 早已定义）。

**新增 dialog**（HistoryQuoteCompletion）手写 `<el-input>` 输入证券代码，没用既有 `<StockCodePicker>`。

## 改动

1. **新增组件** `client/src/components/cells/StockTargetCell.vue`
   - Props: `stockCode` (String) / `showName` (Boolean, default true) / `size` (String, default 'default')
   - 数据: `useStocksStore.stockName(code)`（O(1) Map.get，已 cacheLoaded 响应）
   - T0 徽章: 复用全局指令 `v-t0-badge`
   - `:show-name="false"` 仅显示代码（AdminStockConfig 用）

2. **表格 cell 替换 11 文件 12 处**（dispatches by P1.1 全 grep 收尾）
   - HoldingsPanel / TodayOrdersPanel×2 / T0Trade×2 / CachePositions / CacheOrders / CacheTrades / Dashboard / PositionTable / StkPool（detail）/ AdminStockConfig / HistoryQuoteCompletion

3. **HistoryQuoteCompletion 加分项**
   - 对话 `el-input` → `<StockCodePicker>`（v-model 严格语义：未选中 blur 自动 emit('')，避免非法 code 落库）
   - 表单规则 `pattern` → `validator`：picker 未选中 emit('') 时不再误报 pattern 错

4. **CSS 清理**
   - 删除 7 处 scoped 块冗余的 `.tp-stock-code {...}`（全局 `trade-panel.css:63` 已定义）
   - StkPool 的 `.detail-line / .detail-code / .detail-name` 旧三层结构 CSS 全删（不再用）

5. **utils/stockNames 清理**
   - 5 文件废弃的 `import { stockName } from '../utils/stockNames'` 清掉（T0Trade/CacheOrders/CacheTrades/CachePositions/Dashboard）
   - HoldingsPanel 仍保留（dblclick/click/filter 业务回调还要读名称）

6. **utils/tableColumns.js 注释**
   - STOCK_CODE / STOCK_TARGET 模板文档从"裸 span 字符串"改为 "StockTargetCell"

7. **知识库同步**
   - 知识库/前端/组件/通用组件.md 新增 cells/StockTargetCell.vue 行 + 核心实现段 + 反模式清单

## 影响面

- **无后端改动**
- **无 API 改动**
- **无 store 改动**（仍用现成 stocks store.stockName + v-t0-badge 指令）
- **无路由改动**
- **视觉零差异**：原模板逐字搬迁到组件内部（同样 .text-mono + .tp-stock-code + .text-secondary + v-t0-badge + 6px 间距）

## 验收

| # | 验证 | 结果 |
|---|------|------|
| 1 | `grep "text-mono tp-stock-code"` 全站残留（应只在新组件 + 注释） | 0 业务文件 |
| 2 | 双向 import 校验（用组件但没 import） | 9/9 ✓ |
| 3 | scoped 冗余 `.tp-stock-code` | 0 |
| 4 | `npm run build` (vite build) | ✓ 30.92s 编译通过 |
| 5 | `pytest server/tests/services/quote_sync/` | 10/10 passed |
| 6 | 知识库/前端/组件/通用组件.md 同步 | ✓ |

## 风险

| 风险 | 触发条件 | 后果 | 缓解 |
|---|---|---|---|
| ESM 命名导出 error (v82.5 教训) | StockTargetCell 把方法放 closure 而非顶层 | SPA 整页加载失败 | 组件只导出 setup 函数 + 顶层 `const stockCode = props.stockCode`，无内部 closure export，无 named-import 风险 |
| stocks cache 未 loaded | 新页面第一次打开，cache 加载中 | T0 徽章不显示 / 名称占位 '—' | v-t0-badge 已挂 watcher 兜底，stockName 给 null 由组件显示 '—' |
| StockCodePicker v-model 严格语义未对齐 addRules | 旧 pattern 规则对空字符串报警 | 红色 error 提示 | 改 validator，非空才验 pattern |
