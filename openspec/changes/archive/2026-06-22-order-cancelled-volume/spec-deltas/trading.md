# trading delta — v8 cancelled_volume 主轴推断

## MODIFIED Requirements

### REQ-TRADE-002: 状态推断规则 v8 修订

**Before (v6):**
- 推断规则以 `traded_volume` 为主轴
- `cum_traded == 0` → 49 已报
- `cum_traded < vol` → 50 部成
- `cum_traded == vol` → 51 已成

**After (v8):**
- 推断规则以 `cancelled_volume` 为主轴（broker 主动推送的撤单量更准确）
- 优先序：
  1. `cancelled_volume >= volume` → 53（已撤）
  2. `cancelled_volume > 0 && traded_volume > 0` → 56（部成部撤）
  3. `cancelled_volume > 0`（无成交）→ 53
  4. `broker_status in (52, 53, 54)` → 撤单类信号（兼容老 broker 无 cancelled_volume 字段）
  5. 累计推断：`traded_volume` 决定 49/50/51

## Cross-References

- `data-model/spec.md` §1 cancelled_volume 字段
- `push/spec.md` REQ-PUSH-005 v8 修订
- 实施 commit: `640419a`
