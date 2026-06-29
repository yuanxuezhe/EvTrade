# Tasks: Cache 查看器列宽调整

> 与 [proposal.md](proposal.md) 配套

- [ ] **T1** 改 [client/src/components/CacheTableView.vue](../client/src/components/CacheTableView.vue):
   - `<el-table-column :width>` 改 `:min-width`
   - 加 `:header-cell-style="{ whiteSpace: 'nowrap' }"`（header 单行不换行）
- [ ] **T2** 改 4 个 page view 的 `fields`: 过窄 `width` (80/90/100) 改 `min-width` 或删
- [ ] **T3** 验证：4 页 header 单行；数字列紧凑；长文本列够宽
- [ ] **T4** git commit: `fix(frontend): cache 查看器列宽自适应, 避免 header 换行`
- [ ] **T5** 归档此 change
