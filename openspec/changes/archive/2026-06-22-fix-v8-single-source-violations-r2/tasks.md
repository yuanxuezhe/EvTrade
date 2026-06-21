# Tasks: Fix v8 Single-Source Cache Violations (Round 2)

## 1. 改 Dashboard.vue
- [x] L337-351: 删 orderStore.fetchOrders/fetchTrades (2 行)
- [x] 保留 assetStore.fetchAsset()（assetStore 仍暴露此 action）
- [x] 保留 holdingsStore.bootstrap() 兜底

## 2. 改 Position.vue
- [x] L135-136: 删 orderStore.fetchOrders(stockCode)/fetchTrades(stockCode)
- [x] 改注释说明 v8 由 ws push 增量更新

## 3. 改 AppHeader.vue
- [x] L192-193: 删 orderStore.fetchOrders/fetchTrades
- [x] 保留 assetStore/positionStore fetcher (v8 还没改这俩)

## 4. 验证
- [x] 全项目 grep `orderStore\.(fetch|orders|trades|positions|asset)` = 0 matches

## 5. 提交
- [ ] docs(openspec) 新建 r2 change + spec-delta REQ-FE-009.4
- [ ] fix(client) 删 3 处 orderStore.fetchOrders/fetchTrades 调用 (3 files)
- [ ] docs(openspec) 归档 r2 change
