# positioning spec delta — pos_cfm vol 兜底

**合并到**：`openspec/specs/positioning/spec.md`

## REQ-POS-003 增量

字段映射：
- `row.volume → pos.vol`（**缺字段或为 0 时兜底为 avl_vol**，见 REQ-POS-004）
- `row.available → pos.avl_vol`
- `row.cost_price → pos.cost_price`

## 新增 REQ-POS-004: pos_cfm vol 字段兜底（2026-06-16 立）

- pos_cfm 推送行可能不送 `volume` 字段（只送 `available`）；若 `row.volume` 缺/为 0 而 `row.available > 0`，**vol 兜底为 avl_vol**
- 实现位置：`server/services/push_handlers.py:handle_pos_cfm`
- 测试用例：pos_cfm 推送 `{stock_code:"X", available:100}` 后 `positions.vol == 100`

## 新增 S-POS-002: 推送更新（vol 字段缺失）

Given 柜台推送 pos_cfm 行 `{stock_code:"X", available:100, cost_price:12.5}`（**不送 volume**）
When `handle_pos_cfm` 收到
Then upsert positions 表对应行，`vol = 100`（兜底自 avl_vol）
And `last_vol / today_buy / today_sell` 保持不变（只对账写）

## 新增 S-POS-003: 推送更新（完整字段）

Given 柜台推送 pos_cfm 行 `{stock_code:"X", volume:200, available:150, cost_price:12.5}`
When `handle_pos_cfm` 收到
Then `vol = 200`（不兜底），`avl_vol = 150`
