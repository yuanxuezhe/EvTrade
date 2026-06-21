# Fix v8 Single-Source Cache Violations (Round 2: orderStore.fetchOrders/fetchTrades)

## Why

第 1 轮 (commit `48f1957`) 修了 4 处 `orderStore.{orders,trades}` **数据访问**。
第 2 轮发现 **3 处 `orderStore.fetchOrders/fetchTrades` 函数调用** —— v8 重构 `order.js` 时
**删除了这两个 fetcher**（委托/成交改为 ws push 增量更新），但调用点没同步删。

**症状**：`Uncaught (in promise) TypeError: orderStore.fetchOrders is not a function` at
`Dashboard.vue:344` → Vue mounted hook 崩 → Vue warn chain → SPA 白屏。

## What Changes

- **Dashboard.vue L337-351**: 删 `orderStore.fetchOrders/fetchTrades` 2 行；保留 `assetStore.fetchAsset()`；保留 holdings bootstrap 兜底
- **Position.vue L133-138**: 删 `orderStore.fetchOrders(stockCode)/fetchTrades(stockCode)`；改注释说明 v8 由 ws push 兜底
- **AppHeader.vue L185-194**: 删 `orderStore.fetchOrders/fetchTrades`；保留 `assetStore/positionStore` fetcher（老 store 仍暴露）

## Why not migrate `assetStore.fetchAsset/positionStore.fetchPositions`?

`assetStore` + `positionStore` 还没完成 v8 重构（仍暴露 state + fetcher）。
本次只修**已删除 API 的调用**，避免越界修改 → v9 change 再做架构级迁移。

## Impact

- 受影响的 specs: `frontend/spec.md` REQ-FE-009.3 + 新增 9.4 节（禁止调用 v8 已删除 fetcher）
- 受影响的代码: 3 个 view 文件 (Dashboard / Position / AppHeader)
- 测试: 浏览器访问 Dashboard 不再 TypeError；Position handleSelect 正常；AppHeader 刷新按钮正常
