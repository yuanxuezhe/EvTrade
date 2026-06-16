# data-model spec delta — positions 表 vol 字段说明

**合并到**：`openspec/specs/data-model/spec.md` 第 3 节 `positions` 表

## 业务规则增量

- `vol` 的数据源：pos_cfm 推送 → `row.volume` 字段
  - **缺字段或为 0 时兜底为 `avl_vol`**（2026-06-16 引入）
  - 适用场景：pos_cfm 推送行只送 `available` 不送 `volume`（broker 实际行为）
  - 兜底后 `vol` 一定有值（除非持仓真的为 0）
