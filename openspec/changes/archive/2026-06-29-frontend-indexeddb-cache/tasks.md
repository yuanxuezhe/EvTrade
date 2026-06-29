# Tasks: 4 张业务表 → IndexedDB

> 与 [proposal.md](proposal.md) 配套

- [ ] **T1** 加 `idb` 依赖到 [client/package.json](../client/package.json) 并 `npm install`
- [ ] **T2** 写 [client/src/utils/idbStore.js](../client/src/utils/idbStore.js)：DB open / upgrade / 5 object store 定义 / schema_version 守门
- [ ] **T3** 写 [client/src/utils/cacheRehydrate.js](../client/src/utils/cacheRehydrate.js)：启动时 rehydrate 4 表 → 写回对应 store
- [ ] **T4** 在 [client/src/main.js](../client/src/main.js) 启动序列中调用 rehydrate（**在** Pinia 初始化之后，**在** App mount 之前）
- [ ] **T5** 在 [client/src/stores/asset.js](../client/src/stores/asset.js) `fetchAsset()` 末尾 clear + bulkPut 资金表
- [ ] **T6** 在 [client/src/stores/position.js](../client/src/stores/position.js) `fetchPositions()` 末尾 clear + bulkPut 持仓表
- [ ] **T7** 在 [client/src/stores/holdings.js](../client/src/stores/holdings.js) `bootstrap()` 末尾 clear + bulkPut 委托 + 成交表
- [ ] **T8** 在 [client/src/stores/holdings_push.js](../client/src/stores/holdings_push.js) 5 个 apply* 末尾 upsert by key 增量写 IDB
- [ ] **T9** 验证：`npm run dev` 启动正常；手动测试 rehydrate；改 SCHEMA_VERSION 触发重灌
- [ ] **T10** git commit：`feat(frontend): 资金/持仓/委托/成交 4 张业务表 → IndexedDB 持久化`
- [ ] **T11** 同步 spec delta 到 [openspec/specs/frontend/spec.md](../openspec/specs/frontend/spec.md)
- [ ] **T12** 归档此 change 到 [openspec/changes/archive/2026-06-29-frontend-indexeddb-cache/](../archive/2026-06-29-frontend-indexeddb-cache/)
