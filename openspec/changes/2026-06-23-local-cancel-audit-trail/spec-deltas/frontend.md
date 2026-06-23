# frontend delta — v9 撤单审计前端展示

## NEW Requirements

### REQ-FE-009.5: 撤单审计行（cancel-row）短路

- `holdings.applyOrderPush(row, action)`：见 `row.order_flag === 1` 时**直接 merge + return**，**不**走 `_recomputeStatus`
- 原因：cancel-row `volume=0, traded_volume=0` 会被推算成 `49`（已报）污染显示
- `holdings.applyTradePush(row)`：透传 `trade_type` 字段（0=normal 1=cancel-fill），`trade_type === 1` 时记「撤单审计」日志

### REQ-FE-009.6: 撤单审计视图契约

#### Trade.vue「今日委托」
- 加「类型」列：`order_flag === 1` 渲染 `el-tag type=warning「撤单」`；其他显示「委托」
- 过滤选项新增 `allWithAudit`；默认 `all/pending/filled` **隐藏** cancel-row
- `canCancel(row)` 加 `order_flag === 1` 守卫（cancel-row 不可再撤）
- `pendingCount` 排除 cancel-row

#### Orders.vue「委托查询」
- 加「委托类型」列（区别于「类型」列是 `price_type`）
- `countByStatus` 排除 `order_flag === 1`
- `getFillRate(row)` 加 `order_flag === 1` 守卫直接返 100（volume=0 → 0/0=NaN 修复）

#### Trades.vue「成交查询」
- 加「类型」列：`trade_type === 1` 渲染 `el-tag type=warning「撤单」`；其他显示「成交」
- `buyCount/sellCount/buyAmount/sellAmount` 排除 `trade_type === 1`