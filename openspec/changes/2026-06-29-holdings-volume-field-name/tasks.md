# Tasks: Holdings.vue 持仓量字段名修正

> 与 [proposal.md](proposal.md) 配套

- [ ] **T1** 改 [client/src/views/Holdings.vue](../../client/src/views/Holdings.vue):
   - `<el-table-column prop="volume" ...>` -> `prop="vol"`
   - template 内 `row.volume` -> `row.vol` (如果引用了)
- [ ] **T2** 验证: `grep -n "volume" /client/src/views/Holdings.vue` 只剩非冲突处
- [ ] **T3** git commit
- [ ] **T4** 归档 change
