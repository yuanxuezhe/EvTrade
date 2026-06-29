# Tasks: T0Trade 重新设计 (M-009)

> 与 [proposal.md](proposal.md) 配套

- [ ] **T1** 改 [client/src/views/T0Trade.vue](../client/src/views/T0Trade.vue):
   - template: 简化为 header + 设置条 (标题右侧) + 主表 (含副行 + 操作列) + 底部曲线
   - script setup: 删 3 metric-card / exposure-card / 一键动作 / 配平计算 / 仓位建议 相关代码
   - 保留 useT0Balance / holdingsStore.refreshPositions / onQuickBuy/Sell/Balance 逻辑
- [ ] **T2** 移动端适配: 5 列 -> 4 列 (代码+名称/现价/涨跌/操作), 副行可折叠
- [ ] **T3** 验证: node --check; 1 屏布局正确; 一键动作卡 600519 hardcode 消失
- [ ] **T4** git commit
- [ ] **T5** 同步 spec delta 到 [openspec/specs/frontend/spec.md](../openspec/specs/frontend/spec.md) (新增 REQ-FE-200)
- [ ] **T6** 归档 change
