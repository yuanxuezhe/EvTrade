# Tasks: 去掉 IDB, 纯 Pinia 内存

> 与 [proposal.md](proposal.md) 配套

- [ ] **T1** 删 [client/src/utils/idbStore.js](../client/src/utils/idbStore.js) + [client/src/utils/cacheRehydrate.js](../client/src/utils/cacheRehydrate.js)
- [ ] **T2** 改 [client/src/main.js](../client/src/main.js): 删 rehydrateFromIDB 调用, 恢复直接 app.mount
- [ ] **T3** `npm uninstall idb` 卸包, package.json/lock 自动清
- [ ] **T4** 改 [client/src/stores/asset.js](../client/src/stores/asset.js): fetchAsset 末尾删 bulkReplace + touchLastWrite + import
- [ ] **T5** 改 [client/src/stores/position.js](../client/src/stores/position.js): fetchPositions 末尾删 bulkReplace + import
- [ ] **T6** 改 [client/src/stores/holdings.js](../client/src/stores/holdings.js): bootstrap / refreshAll 末尾删 bulkReplace orders/trades + import
- [ ] **T7** 改 [client/src/stores/holdings_push.js](../client/src/stores/holdings_push.js): 5 个 apply* 末尾删 putItem + import
- [ ] **T8** 重写 [client/src/components/CacheTableView.vue](../client/src/components/CacheTableView.vue): 读 Pinia store ref, 改也改 Pinia, 删 @changed emit, 删 _toPlain
- [ ] **T9** 改 4 page view: 传 store 来源 + keyField
- [ ] **T10** 验证: 5 文件 node --check; 启动 dev 无 IDB 错; 改 cache-viewer 数据, 业务页立即看到
- [ ] **T11** git commit
- [ ] **T12** 同步 spec delta 到 [openspec/specs/frontend/spec.md](../openspec/specs/frontend/spec.md) (删 REQ-FE-100, 改 REQ-FE-101)
- [ ] **T13** 归档此 change
