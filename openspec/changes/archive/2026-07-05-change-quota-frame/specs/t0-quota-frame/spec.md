## ADDED Requirements

### Requirement: T0Trade 顶部 quota frame

T0Trade.vue MUST 在 header 下方、主表上方展示一行 5 个 metric pill：
- 现金余量 = `asset.cash - asset.frozen_cash`
- 冻结资金 = `asset.frozen_cash`
- T+0 可用持仓 = `sum(positions[].avl_vol)`
- 今日已盈亏 = `sum(t0StatsMap[code].realized_pnl)`，跨持仓聚合
- 持仓市值 = `asset.market_value`

#### Scenario: 5 个 pill 都展示

- **WHEN** T0Trade 加载完成，asset / positions / t0StatsMap 都已就绪
- **THEN** quota frame 渲染 5 个 pill，数值取自对应 store 字段
- **AND** pill 数值 MUST 实时响应 store 变化（computed 自动重算）

#### Scenario: T+0 可用持仓 = sum(avl_vol)

- **WHEN** positions = [{stock_code: 'A', avl_vol: 1000}, {stock_code: 'B', avl_vol: 500}]
- **THEN** T+0 可用持仓 pill 显示 `1,500`

#### Scenario: 今日已盈亏含正负号

- **WHEN** t0StatsMap = {A: {realized_pnl: 800}, B: {realized_pnl: -300}}
- **THEN** 今日已盈亏 pill 显示 `+¥500`，绿色
- **WHEN** t0StatsMap = {A: {realized_pnl: -100}}
- **THEN** 今日已盈亏 pill 显示 `-¥100`，红色

#### Scenario: 空数据不报错

- **WHEN** positions = [] 或 t0StatsMap = {}
- **THEN** pill 显示 `0` / `¥0`，不抛错

#### Scenario: 移动端窄屏折叠

- **WHEN** viewport < 1100px
- **THEN** 只展示现金余量 + 今日已盈亏 2 个核心 pill，其它折叠到 popover

### Requirement: T0Trade 行内配额列

T0Trade.vue 主表 MUST 在「浮盈%」列后加 2 列：
- 可买 = `floor((cash - frozen_cash) / last_price / LOT_SIZE) * LOT_SIZE`，按 quoteStore.getLastPrice(row.stock_code) 估算
- 可卖 = `row.avl_vol`

#### Scenario: 可买按 last_price 估算

- **WHEN** row.stock_code = '600030.SH', cash = 100000, frozen_cash = 5000, last_price = 12.5
- **THEN** 可买列显示 `7600` (= floor(95000/12.5/100)*100)

#### Scenario: 可买颜色提示

- **WHEN** 可买 ≥ 1000 → 列绿
- **WHEN** 100 ≤ 可买 < 1000 → 列橙
- **WHEN** 0 < 可买 < 100 → 列红
- **WHEN** 可买 = 0 → 列灰

#### Scenario: 可卖 = avl_vol

- **WHEN** row.avl_vol = 500
- **THEN** 可卖列显示 `500`
- **AND** 颜色按同样阈值（500 橙）

#### Scenario: last_price 未到时可买 = 0

- **WHEN** quoteStore.getLastPrice(row.stock_code) 返回 null/undefined
- **THEN** 可买列显示 `0`，灰显
- **AND** tooltip 提示 "依赖最新价 ¥X"

### Requirement: useT0Quota composable

`client/src/composables/useT0Quota.js` MUST 导出 2 个纯函数 + 1 个 reactive wrapper：

```js
// 纯函数层
aggregateQuota(asset, positions, t0StatsMap) → {
  cashAvail, frozenCash, t0AvailVol, todayPnl, marketValue
}
rowQuota(row, cash, price) → {
  maxBuyable, maxSellable
}

// reactive wrapper
useT0Quota() → {
  aggregate: Ref<QuotaAggregate>,
  rowQuota: (row) => QuotaRow  // 内部调纯函数
}
```

#### Scenario: aggregateQuota 输入 null/空

- **WHEN** asset = null 或 positions = null 或 t0StatsMap = null
- **THEN** 返回所有字段 = 0，不抛错

#### Scenario: aggregateQuota 边界

- **WHEN** cash = 0, frozen_cash = 0, positions = [], t0StatsMap = {}
- **THEN** 返回 `{cashAvail: 0, frozenCash: 0, t0AvailVol: 0, todayPnl: 0, marketValue: 0}`

#### Scenario: rowQuota 输入缺字段

- **WHEN** row 缺 stock_code / vol / avl_vol
- **THEN** 返回 `{maxBuyable: 0, maxSellable: 0}`

#### Scenario: rowQuota 可买按价格扣减

- **WHEN** cash = 100000, price = 12.5
- **THEN** maxBuyable = floor(100000/12.5/100)*100 = 8000
- **WHEN** price = 0 或 null
- **THEN** maxBuyable = 0

#### Scenario: useT0Quota reactive 自动重算

- **WHEN** holdings.cachedAsset.cash 变化
- **THEN** aggregate.value.cashAvail 自动重算
- **AND** 各 row 的 rowQuota(row).maxBuyable 自动重算（依赖 cash）