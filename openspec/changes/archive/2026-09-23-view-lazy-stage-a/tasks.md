# tasks — view-lazy-stage-a

## P0 — 摸清单

- [x] grep view 文件 import 大组件列表, 确认 4 view 范围
- [x] 确认每个组件在 template 用法 (是简单的 `<X />` 还是 v-if / v-for / dynamic :is)
- [x] 不存在 `import X from './X.vue'` 后跟 `import { X as Y }` 同名冲突

## P1 — 4 view 改造

- [x] Trade.vue: 4 子 (OrderForm / QuotePanel / TodayOrdersPanel / HoldingsPanel) 改 defineAsyncComponent
- [x] T0Trade.vue: 7 子 (DataTableView / T0TaskDetail / T0TaskCreateDialog / HoldingsPanel / LivePriceCell / PriceTypeInput / OrderStatusBadge) 改 defineAsyncComponent
- [x] Dashboard.vue: 4 子 (StatCard / EChart / OrderStatusBadge / StockTargetCell) 改 defineAsyncComponent
- [x] Asset.vue: 1 子 (EChart) 改 defineAsyncComponent

## P2 — 验证

- [x] 4 view 文件 curl 看头部有 `defineAsyncComponent`
- [x] `npm run build` 通过
- [x] chunk 大小对比 (build 输出)

## P3 — KB + spec merge + commit

- [x] spec/frontend/spec.md 加 REQ-FE-554
- [x] KB 架构概览加段
- [x] 归档 change → archive/
- [x] commit "feat(frontend): view 私有子组件 defineAsyncComponent 懒加载 (REQ-FE-554)"
