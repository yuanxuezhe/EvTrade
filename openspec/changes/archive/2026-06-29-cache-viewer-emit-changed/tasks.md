# Tasks: cache-viewer 改 IDB 后通知 Pinia

> 与 [proposal.md](proposal.md) 配套

- [ ] **T1** 改 [client/src/components/CacheTableView.vue](../client/src/components/CacheTableView.vue):
   - `onSave` / `onDelete` / `onClear` 成功路径 emit('changed', storeName)
- [ ] **T2** 改 [client/src/views/CacheAsset.vue](../client/src/views/CacheAsset.vue): 接 @changed -> useAssetStore().fetchAsset()
- [ ] **T3** 改 [client/src/views/CachePositions.vue](../client/src/views/CachePositions.vue): 接 @changed -> usePositionStore().fetchPositions() (会同步写 holdings.positions)
- [ ] **T4** 改 [client/src/views/CacheOrders.vue](../client/src/views/CacheOrders.vue): 接 @changed -> useHoldingsStore().refreshAll()
- [ ] **T5** 改 [client/src/views/CacheTrades.vue](../client/src/views/CacheTrades.vue): 接 @changed -> useHoldingsStore().refreshAll()
- [ ] **T6** 验证：5 文件 node --check；手动测 4 页面改动后跳到对应业务页看数据
- [ ] **T7** git commit
- [ ] **T8** 同步 spec delta + 归档
