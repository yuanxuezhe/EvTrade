# Tasks — trade-page-redesign-v2

按依赖顺序, 5 commit 对应 5 个章节。每个章节可独立 revert。

## 1. Trade.vue 清理 + 左列整屏填充 (commit: feat(client))

- [x] 1.1 删 `client/src/views/Trade.vue` 模板顶部 `<div class="trade-quicklinks">` 整行（含 `<el-button text :icon="Refresh" @click="refreshAll" ...>` 节点）
- [x] 1.2 删 `client/src/views/Trade.vue` `<script setup>` 中 `Refresh` 图标 import + `refreshing` ref + `refreshAll()` 函数 + `useHoldingsStore` import + `onMounted` import
- [x] 1.3 加 CSS 规则 `.trade-form-col > * { flex: 1 1 0; min-height: 0; overflow: hidden; }` 让 OrderForm + QuotePanel 等分左列高度；同步删 `.trade-quicklinks` CSS 块
- [x] 1.4 验证: `cd client && npm test -- --run` → 103 单测全过; `cd client && npx vite build` → 构建通过

## 2. mini-panel 加分页 + 精简 (commit: refactor(client))

- [x] 2.1 改 `client/src/components/trade/TodayOrdersPanel.vue`:
  - 删 `<button class="tp-icon-btn" @click="refresh" ...>` 节点
  - 删 `<div v-if="scrollProgress > 0" class="tp-scroll-progress">` 整块
  - 加 `<el-pagination>` (20 行/页, `[10,20,50,100]`) 在 `.tp-body` 之后
  - `<script setup>` 删 `refreshing` ref + `brandPrimary` const + ResizeObserver + scroll listener (`attachScrollListener` / `updateScrollProgress` / `scrollEl` / `resizeObserver`)
  - 加 `page = ref(1)` + `pageSize = ref(20)` + `pagedOrders = computed(...)` slice
  - `<el-table :data="pagedOrders">` (替换 `todayOrders`)
- [x] 2.2 同 2.1 改 `client/src/components/trade/TodayTradesPanel.vue` (无撤单按钮, 列数不变 7 列)
- [x] 2.3 验证单测 103 全过 + 构建通过

## 3. 删 TodayOrders/TodayTrades view + 路由 + sidebar (commit: refactor(client))

- [x] 3.1 删 `client/src/views/TodayOrders.vue` 文件
- [x] 3.2 删 `client/src/views/TodayTrades.vue` 文件
- [x] 3.3 改 `client/src/router/index.js`:
  - 删 `import TodayOrders from '../views/TodayOrders.vue'` 和 `import TodayTrades from '../views/TodayTrades.vue'`
  - 删 `{ path: '/today/orders', name: 'TodayOrders', component: TodayOrders, ... }` 路由项
  - 删 `{ path: '/today/trades', name: 'TodayTrades', component: TodayTrades, ... }` 路由项
  - 改 `{ path: '/orders', redirect: '/today/orders' }` → `{ path: '/orders', redirect: '/history/orders' }`
  - 改 `{ path: '/trades', redirect: '/today/trades' }` → `{ path: '/trades', redirect: '/history/trades' }`
  - 加 `{ path: '/today/orders', redirect: '/history/orders' }` 老书签兼容
  - 加 `{ path: '/today/trades', redirect: '/history/trades' }` 老书签兼容
- [x] 3.4 改 `client/src/components/Sidebar.vue`:
  - `委托查询` 标签 → `历史委托` (path 不变 `/orders`)
  - `成交查询` 标签 → `历史成交` (path 不变 `/trades`)
  - 删除 sidebar 项的 `badge: pendingCount.value > 0 ? pendingCount.value : null` (含括号表达式)
  - 删 `pendingCount` computed 函数
  - 删 `useOrderStore` import + `orderStore` const (dead import after removing pendingCount)
  - 删 `useHoldingsStore` import (only used for pendingCount)
- [x] 3.5 grep 验证: `TodayOrders.vue` / `TodayTrades.vue` / `pendingCount` / `useOrderStore` 在 client/src 残留 0 处（仅保留 panel 组件引用 + 文档注释）
- [x] 3.6 验证单测 103 全过 + 构建通过

## 4. HistoryOrders/HistoryTrades 加预设 chip + 强制历史范围 + 双向高亮 (commit: feat(client))

- [x] 4.1 改 `client/src/views/HistoryOrders.vue`:
  - `<script setup>` 加 `import { shiftDateStr } from '../utils/date'`
  - 加 `todayYYYYMMDD` helper 函数 (本文件 local helper, 基于 `new Date()`)
  - 加 `PRESETS` 常量数组: `[{label:'昨日', offset:1}, {label:'最近三天', start:-3, end:-1}, {label:'最近一周', start:-7, end:-1}, {label:'最近一个月', start:-30, end:-1}]`
  - 加 `presetRange(preset)` 函数返回 `[startYYYYMMDD, endYYYYMMDD]`
  - 加 `setPreset(preset)` 函数: 设 dateRange + 立即 `await runQuery()`
  - 加 `activePreset = computed(() => PRESETS.findIndex(p => sameRange(dateRange, presetRange(p))))`
  - 加 `isAfterToday(date)` 返回 `date >= todayYYYYMMDD(...)` —— 用于 `:disabled-date`
  - `<el-date-picker>` 加 `:disabled-date="isAfterToday"` prop
  - filter-bar 加 4 个 chip 按钮 (`<button :class="{active: activePreset === i}" @click="setPreset(p)">{{p.label}}</button>`), 用 `.filter-chip` + `.filter-chip.active` CSS class
  - `onMounted` 删 `await runQuery()` (留空)
- [x] 4.2 同 4.1 改 `client/src/views/HistoryTrades.vue`
- [x] 4.3 加 `.filter-chip` + `.filter-chip.active` CSS 类 (scoped style, 两个 view 各加一套)
- [x] 4.4 验证单测 103 全过 + 构建通过

## 5. archive change + 同步 3 个 spec 文件 (commit: docs(openspec))

- [x] 5.1 同步 `client/...` 不动 — spec delta 在本 change 内 (`specs/frontend/spec.md`, `specs/orders-trades-history-query/spec.md`, `specs/intraday-orders-trades-cache/spec.md`)
- [x] 5.2 用 `/opsx:archive trade-page-redesign-v2` 归档本 change, 选 "Sync now (recommended)" 把 3 个 spec delta 合并到 main spec
- [x] 5.3 在归档后, 给 `client/src/stores/holdings_bootstrap.js:38` 的 `BOOTSTRAP_WINDOW_DAYS = 1` 加注释: `// v13 trade-page-redesign-v2: 单日窗口即"今日缓存"语义, mini panel 客户端再守门 trd_date === activeDay`
- [ ] 5.4 手动 UI smoke test (若 dev 环境可起) — **apply 阶段不可自动化, 由用户手动验证**:
  - [ ] 登录 → `/trade` 顶部无 quicklinks + 左右列等分
  - [ ] 委托 / 成交 >20 笔 → 出现分页器, 翻页正常
  - [ ] sidebar "委托查询" → "历史委托", 无 badge
  - [ ] `/orders` → 跳 `/history/orders`, 默认空 + 4 chip 出现
  - [ ] 点"最近三天" → 自动查 + chip 高亮
  - [ ] picker 改范围 → chip 高亮即时变化
  - [ ] picker 选 today+ → 不可点
  - [ ] HistoryOrders 列无"操作"列 (no cancel button) — spec 锁验证
