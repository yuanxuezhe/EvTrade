# Position Table Sortable — 持仓表排序扩展（2026-09-18）

## Why

`client/src/components/trade/HoldingsPanel.vue`（T0Trade 页左侧持仓面板）当前显式关闭了 4 个核心数值列的排序能力（`market_value / day_pnl / profit / return_rate` 均标 `sortable: false`）。用户日常需要按这些维度快速找到「市值最大」「当日亏最多」「浮盈最高」「收益率最高」的持仓做调仓/复盘，当前唯一支持排序的列只有 `vol`（持仓数）。

此外，由于 `market_value / profit / return_rate` 是 `holdingsStore` 计算 getter 而非行字段，原 `DataTableView.vue` 仅按 `row[prop]` 排序的逻辑无法处理计算列，必须扩展通用表组件支持自定义 sortFn。

## What Changes

### 1. `client/src/components/DataTableView.vue` — 列定义新增可选 `sortFn`

- 列定义结构增加可选 `sortFn: (row) => any`，用于从行对象派生排序 key
- 客户端排序时**优先**用 `sortFn(row)`，未传则 fallback 到 `row[prop]`（向后兼容，老调用方无感）
- `sortCompare` 逻辑不变（null 兜底 + 数字/字符串两分支）
- 列定义注释 + 顶部 Props 说明补充 `sortFn` 字段
- 新增单测覆盖：有 sortFn 时走 sortFn；无 sortFn 时走 row[prop]

### 2. `client/src/components/trade/HoldingsPanel.vue` — 4 列开启 sortable

| 列 | 现 sortable | sortFn |
|---|---|---|
| 市值 (market_value) | false | `(row) => holdingsStore.getMarketValue(row)` |
| 当日盈亏 (day_pnl) | false | `(row) => row.day_pnl` （行字段已有，写法统一） |
| 浮动盈亏 (profit) | false | `(row) => holdingsStore.getProfit(row)` |
| 收益率 (return_rate) | false | `(row) => holdingsStore.getReturnRate(row)` |

- 4 列 `sortable: false → 'custom'`（DataTableView 默认行为：`sortable: 'custom'` 即排序开关）
- sortFn 通过闭包引用 `holdingsStore`，触发排序时让 el-table 用 prop 回调 → DataTableView `onSortChange` 命中 sortFn
- 行情推送驱动：引用 `quoteTickTrigger` 已存在，保证排序结果随行情刷新（sortFn 调用 getter 自然重读 quote store）

### 3. 知识库同步

`知识库/前端/页面/资产与持仓.md` § 持仓实时市值 后追加"排序能力"小节，说明 4 列可排序 + 排序 key 来源。

## Impact

- **用户可见行为变化**：T0Trade HoldingsPanel 4 列表头可点击排序（升/降/取消 三态）；行情刷新时排序结果实时刷新
- **数据流不变**：v118+ 4 资源数据流（positions broker pos_push 无 IDB / orders-trades IDB 复合 key / asset RPC 5s）不动；holdings/quote store API 不变
- **兼容**：DataTableView sortFn 是可选 prop，所有现存调用方（TodayOrdersPanel / T0Trade 主表 / StkPool 等）零改动
- **后端零改动**：纯前端视图增强

## Files

| 文件 | 改动 |
|---|---|
| `client/src/components/DataTableView.vue` | 列定义加 sortFn 可选字段 + 排序优先用 sortFn + 注释 |
| `client/src/components/trade/HoldingsPanel.vue` | 4 列 sortable 开启 + 各自传 sortFn |
| `client/tests/components/dataTableView_sort.test.js` (新) | 单测：sortFn 优先 + 缺省回退 + null 兜底 |
| `知识库/前端/页面/资产与持仓.md` | 加"排序能力"小节 |

## 引用

- 现状：`openspec/specs/frontend/spec.md` § REQ-FE-220 Scenario: 11 列结构（持仓 sortable on `vol`）
- 现状：`知识库/前端/页面/资产与持仓.md` § 持仓实时市值
- 现状：`openspec/specs/positioning/spec.md` REQ-POS-001（Position 字段语义）

## 验收

- [ ] T0Trade 页 HoldingsPanel 4 列（市值/当日盈亏/浮盈/收益率）表头点击可排序
- [ ] 排序时行情推送到位立即重排（实测：行情到 → 收益率列升序最大值永远在顶）
- [ ] `pytest` 现有基线不破（58/58 通过 → 不变）
- [ ] 前端 `npm run build` 通过
- [ ] DataTableView 现有调用方（TodayOrdersPanel 等）零回归
- [ ] 知识库 `资产与持仓.md` § 持仓实时市值 后追加排序能力说明
