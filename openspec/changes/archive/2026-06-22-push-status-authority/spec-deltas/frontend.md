# frontend delta — push status 防御性重算

## MODIFIED Requirements

### REQ-FE-006: 委托 status 本地推断（前端镜像后端）

**Before:**
- 前端 `applyOrderPush` 收到 `row.status` 后**不重算**，直接信任 broker 透传值
- bootstrap 拉取时**不重算**（line 233 直接赋值 `orders.value = rOrd.value`）

**After:**
- 引入 `_recomputeStatus(o)` helper（`client/src/stores/holdings_helpers.js::recomputeStatus`），逻辑：
  ```js
  function recomputeStatus(o) {
    if (o == null) return o
    if (o.volume == null || o.traded_volume == null) return o
    return { ...o, status: inferOrderStatus(
      { status: o.status, volume: o.volume, traded_volume: o.traded_volume },
      null  // ← 不传 brokerStatus,完全按 cum/vol 算
    )}
  }
  ```
- bootstrap（`holdings_apply_results.js:45`）: `refs.orders.value = rawOrders.map(recomputeStatus)`
- refresh（`holdings_apply_results.js:97`）: `refs.orders.value = rawOrders.map(recomputeStatus)`
- `applyOrderPush`: 改用 `recomputeStatus(row)`，**不传 brokerStatus**

**Why:**
- broker ord_cfm 推 `status="50"`（broker 端"已报"语义），与本地推断 50=部成 语义不一致
- 单纯信任 broker 透传会导致用户报障："成交 0 但显示部成"
- 完全按 `traded_volume/volume` 推断 = 永远符合用户"按已成数量计算状态"诉求

## Cross-References

- `push/spec.md` REQ-PUSH-005 加注：WS 推送 broker 原始 status 是 broker 协议事实，前端展示态以本地推断为准
- 实施 commit: `a6b4f76`（原始 fix）/ `640419a`（推断规则扩展）/ `bcf5811`（重构至 helper 模块）
