## MODIFIED Requirements

### Requirement: T0Trade 视图层结构（REQ-FE-200 增量）

T0Trade.vue MUST 在原 header + 设置条下方、主表上方新增 quota frame 横排 5 个 metric pill (现金余量 / 冻结资金 / T+0 可用持仓 / 今日已盈亏 / 持仓市值)；主表 MUST 在「浮盈%」列后加 2 列配额列 (可买 / 可卖)；移动端 (< 1100px) MUST 折叠为 2 个核心 pill。详细 quota frame / 配额列 / useT0Quota composable 行为场景在 `specs/t0-quota-frame/spec.md` 完整定义。

#### Scenario: quota frame 与现有 header 共存

- **WHEN** T0Trade 加载完成
- **THEN** quota frame 位于 header 设置条 (pct radio + priceType radio + 刷新) 正下方
- **AND** 不挤压 pct radio / priceType radio 宽度

#### Scenario: 配额列与现有主表共存

- **WHEN** T0Trade 主表渲染
- **THEN** 「可买」「可卖」2 列插入「浮盈%」与「操作」之间
- **AND** 不改变现有列宽（仅操作列宽可微调 ±10px 补偿）

#### Scenario: 不破坏排序 / 快捷键 / 抽屉

- **WHEN** trader 按 B / S / P / ↑ / ↓ / Enter 快捷键
- **THEN** 排序与快捷键行为与 quota frame 引入前一致
- **WHEN** trader 点击行打开抽屉
- **THEN** 抽屉内容（stats + 累计曲线 + 累计统计）与 quota frame 引入前一致