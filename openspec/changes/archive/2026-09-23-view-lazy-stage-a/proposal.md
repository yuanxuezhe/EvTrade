# view-lazy-stage-a（view 私有 store + 子组件 defineAsyncComponent）— 2026-09-23

## 解决什么

REQ-FE-551/552/553 已把 main + layout + 业务 file element-plus 整包 import 全清, 但**路由 lazy 解析后, 每个 view 内部仍 eager import**:

- `Trade.vue` (237 lines) → `OrderForm` + `QuotePanel` + `TodayOrdersPanel` + `HoldingsPanel` 4 个大组件
- `T0Trade.vue` (1272 lines) → `DataTableView` + `T0TaskDetail` + `T0TaskCreateDialog` + `HoldingsPanel` + `LivePriceCell` + `PriceTypeInput` + `OrderStatusBadge` 7 个组件 + 4 个 view 私有 store
- `Dashboard.vue` (569 lines) → `StatCard` + `EChart` (echarts) + `OrderStatusBadge` + `StockTargetCell`
- `Asset.vue` (419 lines) → `EChart` (echarts)
- `ScriptDev.vue` (668 lines) → `CodeEditor` (CodeMirror 6 dist ~1 MB)
- `ScriptTask.vue` → 也许 echarts
- `HistoryQuoteCompletion` (457 lines) → `StockCodePicker`
- `StkPool.vue` (710 lines) → 多子组件
- `StkPoolView.vue` (414 lines)
- `Users.vue` (420 lines) → `userApi`
- `ScriptTask.vue` (658 lines)

实测 `npm run build` chunk 大小:
- `ScriptTask-DciGcsqn.js` 517 KB / 170 KB gzip — 已被 codemirror / echarts 重填充
- `ScriptDev-*.js` 476 KB / 160 KB gzip — 同上
- `T0Trade-CfQYHB55.js` 34 KB
- `Trade-DWOnHeDi.js` 16 KB

## 改动 — Stage A

A 阶段专注 view 私有 store 拆 lazy + 子组件 defineAsyncComponent, **不影响 view 主页使用, 仅拆粗**:

### 1. view 私有 store: 路由到 view 后才 import

`T0Trade.vue` 引 4 个 store 当前在 setup 顶层 `useXxxStore()`:
```js
// 当前
import { useT0TasksStore } from '../stores/t0_tasks'
import { useStocksStore } from '../stores/stocks'
...
const t0TasksStore = useT0TasksStore()
```

改为: store 仍保留 eager import (lazy store 太复杂, 不可行), **不动** — Stage A 范围只动组件 + 计算 + 子模块.

### 2. view 私有子组件 defineAsyncComponent

```vue
<script setup>
// 当前
import OrderForm from '../components/OrderForm.vue'
import TodayOrdersPanel from '../components/trade/TodayOrdersPanel.vue'

// 改为
import { defineAsyncComponent } from 'vue'
const OrderForm = defineAsyncComponent(() => import('../components/OrderForm.vue'))
const TodayOrdersPanel = defineAsyncComponent(() => import('../components/trade/TodayOrdersPanel.vue'))
</script>
```

`<template>` 用法不变, 仍是 `<OrderForm ref="orderFormRef" ... />`. defineAsyncComponent 自动延迟 chunk fetch, 渲染前/后 vite dev 都正常.

### 3. 适用 view 范围 (Stage A)

4 view 文件 (Trade 4 子 + T0Trade 7 子, 其它 view 在 Stage B/C/D 处理):
- `Trade.vue` — 4 子组件
- `T0Trade.vue` — 7 子组件
- `Dashboard.vue` — 4 子组件 (含 echarts 来源 EChart)
- `Asset.vue` — 1 子组件 (EChart)

## 不做 (Stage B/C/D 拍板)

- Stage B: T0Trade / Trade 复杂子组件按业务时序 lazy (e.g. T0TaskCreateDialog 只在用户点"新建"时才 fetch)
- Stage C: Dashboard / Asset EChart lazy
- Stage D: ScriptDev / ScriptTask CodeMirror lazy (最大潜在收益 ~1MB)

## 影响面

- 仅 frontend 4 view 文件改动
- 路由 / store / API / view template 用法 0 改动 (defensive)

## 验证

1. `curl Trade.vue / T0Trade.vue / Dashboard.vue / Asset.vue` 看头部有 defineAsyncComponent
2. `npm run build` Trade / T0Trade / Dashboard / Asset 4 个 chunk 大小应减少
3. vite dev 手测 4 个路由关键功能不挂
