# T0 敞口聚合 + 累计收益 + 真实已实现

## Why

v7 schema 完成、`Order.user_def` 字段已透传后，T0Trade.vue 已能按 `user_def='T0'` 给单笔委托打标签。但 T0 的**报表视角**仍停留在单标的 (`t0-stats/{code}`) / 单标的历史 (`t0-history/{code}`)，**无法回答用户三个核心问题**：

1. **"今天我按 T0 标签总共买了多少、卖了多少、净敞口是多少？"** —— 当前要去 `t0-stats` 逐个股票看，无聚合
2. **"做T 累计收益率是多少？胜率多少？"** —— 现有 `t0-history` 只算 `sell_amt - buy_amt` 毛流，不扣费、不算持仓成本基准
3. **"某个标的按 T0 净买入 200 股，我需要一键卖出 200 股"** —— 当前必须自己先看 `t0-stats` 然后手动输入数量

同时 `t0-stats` 的 `realized_pnl` 算式有 bug（`server/api/t0_stats.py:108-115`）：用"当日买均价 vs 当日卖均价"的价差算盈亏，**忽略持仓成本基准、忽略手续费/印花税**。这对真实做T 来说算出来的是"价差毛利"，不是真实利润。

## What Changes

### 1. 新增后端聚合服务

- **新增文件** `server/services/t0_aggregate.py`：
  - `calc_realized_pnl(sell_trades, cost_basis, fee_cfg) -> (realized, commission, stamp_tax)`
  - `calc_net_exposure(orders, trades) -> (net_volume, buy_vol, sell_vol, buy_amt, sell_amt)`
  - `aggregate_by_stock(trades, orders, positions, fee_cfg) -> List[ExposureRow]`
  - `aggregate_by_day(trades, positions, fee_cfg, days) -> List[DayRow]`
  - `aggregate_summary(by_day, by_stock) -> Summary`

- **新增文件** `server/api/t0_aggregate.py`：
  - `GET /api/orders/t0-exposure?user_def=T0&trd_date=YYYYMMDD` — 多标的当日敞口
  - `GET /api/orders/t0-aggregate?user_def=T0&days=30` — 跨期累计 + 按日/按股双视角

- **修改文件** `server/api/t0_stats.py`：
  - 修 `realized_pnl` 算式（用 `calc_realized_pnl`，基于 `Position.cost_price` + 卖出 Trade 列表）
  - `unrealized_pnl` 含义改为"持仓浮动盈亏"（基于 cost_basis × 当前持仓 vs 最新价，**不**包含今日已实现）

### 2. 修 t0.py 注释（FeeConfig 现在已有 min_commission/slippage）

- 修 `server/services/t0.py:84` 注释
- `calc_commission` 增加 `min_commission` 兜底（commission < min_commission 时取 min_commission）

### 3. 前端集成

- `client/src/api/t0_stats.js`：
  - 新增 `getExposure({ user_def, trd_date })`
  - 新增 `getAggregate({ user_def, days })`

- `client/src/composables/useT0Balance.js`：
  - 新增 `exposureList` / `aggregate` reactive + `loadExposure()` / `loadAggregate()`

- `client/src/views/T0Trade.vue`：
  - 新增组件位置（在 3 卡片下方、操作区上方）：
    - `<T0ExposureTable>`：每个 T0 标的的买/卖/敞口/一键配平
    - `<T0AggregateCard>`：累计已实现 / 回报率 / 胜率
  - 一键配平按钮：传 `submitOrder({ orderType, volume: |net_vol|, price: latest })` + `user_def='T0'`
  - 全账户一键配平（按 totals.net_volume 选买卖方向后下 1 单）

### 4. spec 同步

- `openspec/specs/trading/spec.md` REQ-TRADE-006 已新增（含端点契约 + 算法）
- `openspec/specs/frontend/spec.md` 需补 REQ-FE 规则（前端如何消费 t0-exposure/aggregate）

## Non-Goals

- 不改 `t0-stats/{code}` / `t0-history/{code}` 的 URL / 字段名（仅修 realized 算式，加 BREAKING 注释）
- 不动 `Order.user_def` 字段含义（已 v7 完成）
- 不动 ORM schema（无新增列）
- 不动 msgpacket RPC 协议
- 不实现实时累计推送（仅 WS 推单笔成交事件，聚合靠前端拉接口）

## Impact

- **后端**：3 个新文件（`t0_aggregate.py` / `api/t0_aggregate.py` / `test_t0_aggregate.py`），改 1 个（`t0_stats.py` realized 算式 + 注释）
- **前端**：1 个新 API 文件扩展（`t0_stats.js`），1 个 composable 扩展（`useT0Balance.js`），1 个 view 改（`T0Trade.vue`）
- **数据**：0 改动（用现有 Order/Trade/Position/Asset 表）
- **DB migration**：0（无需新表）
- **RPC**：0 改动（不调新 RPC）

## Verification

- `pytest server/test_t0_aggregate.py` 全绿（≥ 8 用例：算法 3 + 端点 5）
- `pytest server/test_t0.py` + `pytest server/test_t0_stats.py` 全绿
- 手动：`curl http://localhost:8000/api/orders/t0-exposure?user_def=T0&trd_date=20260619 -H "Authorization: Bearer ..."` 返回正确 JSON
- 手动：T0Trade.vue 刷新看到敞口表 + 累计卡

## Dependencies

- 依赖 v7 schema（已 commit `055a7ba`，在 master）
- 依赖 `t0.py` 的 `get_fee_config()` 已有（无需改）
- 前端依赖 `useT0Balance.js` 已有（无需重写）
