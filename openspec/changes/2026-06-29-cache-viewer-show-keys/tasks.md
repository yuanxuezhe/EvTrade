# Tasks: Cache 查看器列名加英文 key

> 与 [proposal.md](proposal.md) 配套

- [ ] **T1** 改 [client/src/components/CacheTableView.vue](../client/src/components/CacheTableView.vue):
   - `<el-table-column :label="f.label">` 改为 `:label="displayLabel(f)"`
   - `<el-form-item :label="f.label">` 同样
   - 加 `displayLabel(f)` helper 返回 `"${f.label} (${f.key})"`
- [ ] **T2** 验证：4 个 page view 不改，列名应自动带 key 后缀
- [ ] **T3** git commit: `feat(frontend): cache 查看器列名带英文 key 后缀`
- [ ] **T4** 同步 spec delta → [openspec/specs/frontend/spec.md REQ-FE-101](../openspec/specs/frontend/spec.md)
- [ ] **T5** 归档此 change
