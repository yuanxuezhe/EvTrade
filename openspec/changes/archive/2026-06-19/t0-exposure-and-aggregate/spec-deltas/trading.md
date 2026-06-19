# Spec Delta — trading

见 `openspec/specs/trading/spec.md` 的 `### REQ-TRADE-006: T0 敞口与累计收益（v1）` 章节。

## 新增端点
- `GET /api/orders/t0-exposure?user_def=T0&trd_date=YYYYMMDD`
- `GET /api/orders/t0-aggregate?user_def=T0&days=30`

## BREAKING（`t0-stats` 算式）
- `realized_pnl`: 旧 = (sell_avg - buy_avg) × paired；新 = (sell_avg - cost_basis) × min(sell_vol, position_vol) - sell_commission - sell_stamp_tax
- `unrealized_pnl`: 旧 = (sell_avg - cost_basis) × min(sell_vol, position_vol)；新 = (latest_price - cost_basis) × position_vol（基于当前持仓 × 最新价）
