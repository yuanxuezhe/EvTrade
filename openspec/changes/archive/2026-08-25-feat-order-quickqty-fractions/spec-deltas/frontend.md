# frontend delta

## ADDED Requirements

### Requirement: OrderForm 委托数量快捷按钮 = 可用分数（2026-08-25）

The `client/src/components/OrderForm.vue` SHALL 把委托数量的 5 个快捷按钮从**绝对股数** `[100, 500, 1000, 5000, 10000]` 改为**可用数量分数** `[1/10, 1/5, 1/4, 1/2, 1/1]`。

每点击一个分数按钮，委托数量 SHALL 按下列规则计算并写入 `form.volume`：

**买入方向（order_type=23，可用 = 资金上限）**：
1. `available_raw = assetStore.asset.cash / px`（px 按价格类型分 FIX/LATEST/MARKET_PEER，见现有 `availableText` 计算）
2. `volume_raw = available_raw × fraction`
3. 整手取整：**向下取整** `floor(volume_raw / trade_unit) * trade_unit`
4. 不允许超过 `available_raw`（fraction 截断后 ≤ available_raw）

**卖出方向（order_type=24，可用 = 持仓 avl_vol）**：
1. `available_raw = positionStore.positions[stock_code].avl_vol`
2. `volume_raw = available_raw × fraction`
3. 整手取整：**向上取整** `ceil(volume_raw / trade_unit) * trade_unit`（不超 `available_raw`）
4. 截断到 0：若 `volume_raw < trade_unit` → 0（不可下零手）

**trade_unit 来源**：`stocksStore.stockTradeUnit(stock_code)`（新增 helper，cache miss 兜底 100）。不同品种（ETF 部分是 1 / 10 / 1000）按各自 trade_unit 整手。

**按钮展示**：
- 按钮文案 = 分数 `{{ fraction.label }}`（如 `1/2`）
- `title` 属性 = 具体股数（动态计算，如 `"1/2 = 2500 股 (按可用 5000)`）
- `:disabled="availableTradeQty <= 0"`（无可用时禁用）

#### Scenario: 买入 1/2

- **GIVEN** 用户切到买入，cash=50000, price=10, trade_unit=100
- **WHEN** 点 `1/2` 按钮
- **THEN** `form.volume = 2500`（= 5000 × 0.5，整手 100 向下取整不变）
- **AND** 按钮 title = "1/2 = 2500 股 (按可用 5000)"

#### Scenario: 卖出 1/2

- **GIVEN** 用户切到卖出，avl_vol=3000, trade_unit=100
- **WHEN** 点 `1/2` 按钮
- **THEN** `form.volume = 1500`（= 3000 × 0.5，整手 100）

#### Scenario: 卖出 1/10 不足 1 手

- **GIVEN** 用户切到卖出，avl_vol=85, trade_unit=100
- **WHEN** 点 `1/10` 按钮
- **THEN** `form.volume = 0`（8.5 股不足 1 手）

#### Scenario: 切换买卖方向重算

- **GIVEN** 用户先点买入 1/2（form.volume=2500），然后切到卖出
- **WHEN** 用户点卖出 `1/2`
- **THEN** `form.volume` 重新计算为 卖出方向的 1/2 股数（不继承买入值）

#### Scenario: 无可用时禁用

- **GIVEN** 用户切到卖出，但无持仓（positionStore 无该 stock_code）
- **WHEN** 渲染分数按钮
- **THEN** 5 个按钮均 `:disabled`，title = "无可用持仓"

#### Scenario: trade_unit = 1（部分 ETF）

- **GIVEN** trade_unit = 1（如部分跨境 ETF）
- **WHEN** 买入 1/2 cash/px=1500, fraction=0.5 → raw=750
- **THEN** `form.volume = 750`（trade_unit=1 不影响结果，floor(750)=750）

### Requirement: stocksStore.stockTradeUnit helper（2026-08-25）

The `client/src/stores/stocks.js` SHALL 提供 `stockTradeUnit(code)` helper：

- 签名同 `stockScale(code)` / `stockStktype(code)`（已存在）
- 输入 `stock_code`，输出 `number`（默认 100）
- cache miss 或 stock 未在 cache 中 → 兜底 100（A 股 1 手）
- `trade_unit` 字段为 null/undefined/0 → 兜底 100
- 校验范围：0 < trade_unit ≤ 100000，超界 → 兜底 100

该 helper 必须从 store return 块导出（与 `stockScale` / `stockStktype` 并列）。

#### Scenario: stockTradeUnit 返回真实值

- **GIVEN** cache 中 stock_code='510300.SH' 的 `trade_unit = 1`
- **WHEN** 调 `stocksStore.stockTradeUnit('510300.SH')`
- **THEN** 返回 1

#### Scenario: cache miss 兜底 100

- **GIVEN** cache 中无 stock_code='999999.SH'
- **WHEN** 调 `stocksStore.stockTradeUnit('999999.SH')`
- **THEN** 返回 100

#### Scenario: trade_unit = null 兜底

- **GIVEN** cache 中 stock.trade_unit = null
- **WHEN** 调 helper
- **THEN** 返回 100（不返 null，避免下游除零 / NaN）

### Requirement: 不变项

- OrderForm 其他字段（标的、价格、价格类型）行为不变
- `applyAvailableToVolume`（双击可交易数量）行为不变
- `form.volume` 默认 100 与 `:min="100"` `:step="100"` 不变（最低限兜底）
- 不动 T0Trade / StrategyOrder 页面
- 后端 API / store 接口 / WS 频道不变