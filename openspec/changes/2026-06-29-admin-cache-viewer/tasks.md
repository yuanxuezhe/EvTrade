# Tasks: Admin 缓存查看器

> 与 [proposal.md](proposal.md) 配套

- [ ] **T1** 写 [client/src/components/CacheTableView.vue](../client/src/components/CacheTableView.vue)：通用表格组件 (storeName + fields + 可选 actions: edit/add/delete/clear)
- [ ] **T2** 写 [client/src/views/CacheAsset.vue](../client/src/views/CacheAsset.vue)：资金表，只允许改 (CRUD 中禁用 add/delete)
- [ ] **T3** 写 [client/src/views/CachePositions.vue](../client/src/views/CachePositions.vue)：持仓表，全 CRUD
- [ ] **T4** 写 [client/src/views/CacheOrders.vue](../client/src/views/CacheOrders.vue)：委托表，全 CRUD
- [ ] **T5** 写 [client/src/views/CacheTrades.vue](../client/src/views/CacheTrades.vue)：成交表，全 CRUD
- [ ] **T6** 在 [client/src/router/index.js](../client/src/router/index.js) 加 4 个路由 (都 `meta.requiresAdmin: true`)
- [ ] **T7** 在 [client/src/AppHeader.vue](../client/src/AppHeader.vue) admin 区加子菜单 "缓存查看 → 资金/持仓/委托/成交"
- [ ] **T8** 验证：4 文件 `node --check`；路由不冲突；admin / non-admin 测试
- [ ] **T9** git commit：`feat(frontend): admin 缓存查看器 (4 路由 + 1 通用表格组件)`
- [ ] **T10** 同步 spec delta 到 [openspec/specs/frontend/spec.md](../openspec/specs/frontend/spec.md)
- [ ] **T11** 归档此 change 到 [openspec/changes/archive/2026-06-29-admin-cache-viewer/](../archive/2026-06-29-admin-cache-viewer/)
