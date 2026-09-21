# frontend — REQ-FE-540: HoldingsPanel 4 列 sortable

> 增量改动。`openspec/specs/frontend/spec.md` 末尾追加 REQ-FE-540。

## REQ-FE-540: HoldingsPanel 4 列 sortable (2026-09-18)

The system SHALL 让 `client/src/components/trade/HoldingsPanel.vue` 的 4 个数值列（市值 / 当日盈亏 / 浮动盈亏 / 收益率）支持表头点击排序，且排序结果随行情推送实时刷新。

### Scenario: 4 列默认开启 sortable='custom'

- **GIVEN** user 在 T0Trade 页查看 HoldingsPanel
- **WHEN** 表格渲染
- **THEN** `market_value / day_pnl / profit / return_rate` 4 列 MUST 显示 el-table sortable 标识（hover 表头出箭头）
- **AND** 列定义 MUST 显式 `sortable: 'custom'`（DataTableView 默认行为，4 列覆盖原 `false`）
- **AND** 前 6 列（标的/期初/持仓/可用/成本/最新价）保持原样：`stock_code/last_vol/vol/avl_vol/cost_price` 默认 sortable='custom'，`last_price` 仍 `sortable: false`（LivePriceCell 不参与排序）

### Scenario: 计算列通过 sortFn 派生排序 key

- **GIVEN** HoldingsPanel 的 4 个目标列
- **WHEN** DataTableView `sortedData` 计算
- **THEN** 4 列 MUST 通过列定义 `sortFn: (row) => <calc>` 派生排序值：
  - `market_value` → `holdingsStore.getMarketValue(row)` （实时价 × vol）
  - `day_pnl` → `row.day_pnl` （行字段，由 holdings_daypnl recomputeAll 写入）
  - `profit` → `holdingsStore.getProfit(row)` （含当日扣费浮动盈亏）
  - `return_rate` → `holdingsStore.getReturnRate(row)` （profit / 成本市值）
- **AND** DataTableView 客户端排序 MUST 优先用 sortFn(row)，未传时 fallback 到 row[prop]（向后兼容）
- **AND** sortFn 调用 getter 时 MUST 经由 `void quoteTickTrigger.value` 触发响应式（行情推送到位时排序结果实时刷新）

### Scenario: DataTableView sortFn 是可选 prop（向后兼容）

- **GIVEN** 任意 DataTableView 调用方（TodayOrdersPanel / T0Trade 主表 / StkPool 等）
- **WHEN** 列定义未传 `sortFn`
- **THEN** MUST fallback 到 `row[col.key]` 排序（与改动前行为完全一致）
- **AND** 调用方代码 MUST 零改动

### Scenario: null / undefined 排序值兜底（继承原 DataTableView 行为）

- **GIVEN** 某行 `getMarketValue` 返回 null（行情未到）
- **WHEN** 按市值升序排序 (dir=+1)
- **THEN** null 行 MUST 排在末尾（`va=null` → return dir=1 → null 视为更大）
- **WHEN** 按市值降序排序 (dir=-1)
- **THEN** null 行 MUST 排到首位（`va=null` → return dir=-1 → null 视为更小；与原 el-table 行为一致）
- **AND** 此行为与原 DataTableView 完全一致（向后兼容, 详见 `client/src/utils/tableSort.js` 注释）

### Scenario: 单测覆盖

- `client/tests/utils/tableSort.test.js` MUST 包含至少 3 case：
  - 有 sortFn 时优先用 sortFn 返回值
  - 缺 sortFn 时用 row[prop]
  - null 兜底：升序 `[5, null]` → `[5, null]`; 降序 `[5, null]` → `[null, 5]`（继承原行为）
