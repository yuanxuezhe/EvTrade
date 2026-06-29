# Holdings.vue 持仓量字段名修正

> 创建日期：2026-06-29
> 状态：draft
> 范围：client/src/views/Holdings.vue (1 文件)

## Why

**用户报**："持仓查询持仓量值为0，但是缓存中，总持仓有值。总持仓就是持仓量"

**根因诊断**（[systematic-debugging](skills/systematic-debugging) 步骤 1-2）：

| 字段 | server 返 | Holdings.vue 显示 | 缓存表显示 |
|---|---|---|---|
| 持仓量 | `vol` | `row.volume` ❌ | `vol` ✓ |
| 可用 | `avl_vol` | `row.avl_vol` ✓ | `avl_vol` ✓ |
| 期初 | `last_vol` | `row.last_vol` ✓ | `last_vol` ✓ |

Holdings.vue 的 `<el-table-column prop="volume" label="持仓量">` 用 `volume`，但 server 实际返的是 `vol`（无 `ume`）。结果：`row.volume` 是 `undefined` → `formatNumber(undefined)` 渲染为 0/空。

**全仓对比验证**：
- `Dashboard.vue` `prop="vol"` ✓
- `PositionTable.vue` `prop="vol"` ✓
- `T0Trade.vue` `row.vol` ✓
- `Position.vue` `p.vol` ✓
- `PositionDetail.vue` `position.vol` ✓
- `holdings_market.js` `p.vol` ✓
- `holdings_push.js` `row.vol` ✓
- `CachePositions.vue` 字段定义 `key: 'vol'` ✓
- `Holdings.vue:243` CSV 导出 `p.vol` ✓
- **`Holdings.vue:30` 表格 column `prop="volume"` ❌** —— 唯一错误

是早期复制代码时的 typo。

## What

只改 [client/src/views/Holdings.vue](../../client/src/views/Holdings.vue) 的 1 行 column prop：
- `prop="volume"` → `prop="vol"`
- 内部 `row.volume` → `row.vol` (template 中)
- CSV 导出已对 (`p.vol`)，不动

## 影响的 capability

- `frontend` — REQ-FE-001 (持仓查询视图) 字段名对齐

## 验证

- 打开 `/holdings` → "持仓量" 列显示真实数值（之前是 0/空）
- 导出 CSV 仍能正常工作（"持仓量"列 = `p.vol`）
- 在 `/admin/cache/positions` 改 `vol` 数值 → 跳到 `/holdings` → 显示一致
