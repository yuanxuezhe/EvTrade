# REQ-FE-009.4: 禁止调用 v8 已删除的 fetcher

## ADDED Requirements

### REQ-FE-009.4 (禁止调用)

`orderStore` v8 重构后**删除**以下 API（v9 之前不重新暴露）：

- ❌ `orderStore.fetchOrders()` — 委托由 ws `order_update` push 兜底
- ❌ `orderStore.fetchOrders(stockCode)` — 单股委托同理
- ❌ `orderStore.fetchTrades()` — 成交由 ws `trade_update` push 兜底
- ❌ `orderStore.fetchTrades(stockCode)` — 单股成交同理

**MUST**: 委托/成交加载走 `holdingsStore.bootstrap()` (App 启动) 或 `holdingsStore.refreshAll()` (手动刷新)。
持仓/资金由 `holdingsStore.bootstrap()` 一次性拉，ws push 增量更新。

#### Scenario

Given a view component imports `useOrderStore`
When calling `orderStore.fetchOrders` / `orderStore.fetchTrades`
Then Vue mounted hook → TypeError: X is not a function → render 崩 → SPA 白屏

#### Fix Sites

- `Dashboard.vue` L337-351: 删 fetcher 调用 → 保留 assetStore.fetchAsset + holdings bootstrap 兜底
- `Position.vue` L133-138: 删 handleSelect 内的 fetcher → 走 ws push
- `AppHeader.vue` L185-194: 删 handleRefresh 内的 fetcher → holdingsStore.refreshAll() 已含
