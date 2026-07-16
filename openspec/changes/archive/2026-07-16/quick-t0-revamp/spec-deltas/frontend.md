# spec-deltas/frontend.md — REQ-FE-220

> 增量 spec：`frontend` capability
> 对应 changeset：`2026-07-16-quick-t0-revamp`
> 合并目标：`openspec/specs/frontend/spec.md`（在 REQ-FE-210 之后）

---

## REQ-FE-220: T0Trade 主表重构（做T盈亏 / 敞口 / 期初配额 / 做T收益率%）

### 背景

`client/src/views/T0Trade.vue` 现有 1176 行实现存在 4 类问题：

1. **做T盈亏口径错位** — 后端 `t0-stats/{code}` 的 `realized_pnl` 用 v6 算法（基于持仓成本基准 + 费用），trader 直觉口径应为 `SUM(卖 vol*price) - SUM(买 vol*price)`。
2. **配平价格档语义错位** — 配平按钮沿用 quick 价格档（last/market/bidask），但配平应使用对手盘价（买敞口→卖1、卖敞口→买1）。
3. **可买可卖基数错** — `useT0Quota.rowQuota` 用 `cash/avl_vol` 算可买可卖，做T场景下应基于 **期初持仓**（`last_vol`）递减已成交。
4. **价格展示精度硬卡 2 位** — `formatPrice(x, 2)` 把 0.0039 砍成 "0.00"，做T人对 1-2 分钱敏感。

### 范围

`T0Trade.vue` 主表 11 列重做 + `lib/t0-calc.js` 新增 6 纯函数。

### 需求

The system SHALL render `client/src/views/T0Trade.vue` 主表为 11 列结构，按下表顺序：

| # | 列名 | 数据来源 | 公式 | 颜色规则 |
|---|---|---|---|---|
| 1 | 代码 | `row.stock_code` | — | — |
| 2 | 名称 | `stockName(code)` | — | — |
| 3 | 期初 | `row.last_vol` | `formatNumber(last_vol)` 整百对齐 | 灰 |
| 4 | 现价(涨跌幅) | `quoteStore` | `formatPriceAuto(last_price) (formatPercent(change_pct))` 合并为单列 | 涨红/跌绿 |
| 5 | 已买 | `stats.today_buy_volume` | `formatNumber(vol)` | 灰 |
| 6 | 已卖 | `stats.today_sell_volume` | `formatNumber(vol)` | 灰 |
| 7 | 敞口 | `calcExposure(row, stats)` | `last_vol + today_buy - today_sell` | >0 红（多敞口）/ <0 绿（空敞口）/ 0 灰 |
| 8 | 做T盈亏 | `calcT0Pnl(stats)` | `today_sell_amount - today_buy_amount` | >0 红 / <0 绿 / 0 灰；无成交 → `--` |
| 9 | 做T收益率% | `calcT0ReturnRate(row, stats)` | `(sell_amount - buy_amount) / (last_vol * cost_price)` | >0 红 / <0 绿 / 0 灰；last_vol 或 cost_price 为 0 → `0.00%` |
| 10 | 可买/可卖 | `calcInitialQuota(row, stats)` | `max(0, last_vol - today_buy) / max(0, last_vol - today_sell)` | 数字字色不变 |
| 11 | 操作 | 4 按钮 | 买X% / 卖X% / 配平 / 详情 | 见按钮逻辑 |

#### Scenario: 主表 11 列结构验证

- **GIVEN** trader 登录并 navigate `/t0-trade`，持仓非空
- **WHEN** 渲染主表
- **THEN** MUST 11 列按顺序：代码 / 名称 / 期初 / 现价(涨跌幅) / 已买 / 已卖 / 敞口 / 做T盈亏 / 做T收益率% / 可买/可卖 / 操作
- **AND** 第 4 列（现价+涨跌幅）合并显示为 `10.50 (+0.50%)` 格式（涨）/ `10.50 (-0.30%)` 格式（跌）
- **AND** 第 8 列做T盈亏 = `stats.today_sell_amount - stats.today_buy_amount`
- **AND** 第 9 列做T收益率% 单位为百分比（0.05 → `5.00%`）
- **AND** 第 10 列可买/可卖基于 `last_vol` 递减，**不** 基于 `cash` 或 `avl_vol`

#### Scenario: 配平按钮使用对手盘价

- **GIVEN** trader 选中持仓 000001.SZ，行情已有 `ask_prices[0]=11.50` / `bid_prices[0]=11.20`
- **WHEN** 今日净买 300 股（多敞口）→ 点配平按钮
- **THEN** 系统 MUST 用 `bid_prices[0]`（买1价 11.20）下单卖出 300 股，**不** 用最新价或 bidask 价格档
- **AND** tooltip MUST 显示"配平: 卖300 用买1价 11.20"
- **WHEN** 行情未到（ask_prices/bid_prices 为空）
- **THEN** 系统 MUST fallback 到 `last_price`，并 tooltip 标记 `[fallback]`

#### Scenario: 价格展示 4 位小数

- **GIVEN** 持仓 113039.SH 可转债，最新价 0.0039
- **WHEN** 渲染现价列
- **THEN** MUST 显示 `0.0039`（4 位小数），**不** 显示 `0.00`
- **AND** `formatPriceAuto` 规则：0 → `0`，100 → `100`，12.5 → `12.5`，12.00 → `12`，0.0039 → `0.0039`

#### Scenario: 做T盈亏口径

- **GIVEN** trader 早盘 10:00 买 100 股 @ 10.00（today_buy_amount=1000）+ 下午 14:00 卖 100 股 @ 10.50（today_sell_amount=1050）
- **WHEN** 渲染做T盈亏列
- **THEN** MUST 显示 `+50.00`，颜色红
- **AND** MUST NOT 扣减持仓成本基准或费用（这是做T人口径，**不** 等同于 v6 realized_pnl）

#### Scenario: 做T收益率% 公式

- **GIVEN** 期初持仓 1000 股 @ 成本 10.00（cost_total=10000）
- **WHEN** 做T盈亏 = +500
- **THEN** 做T收益率% MUST = `500 / 10000 = 5.00%`
- **WHEN** 期初持仓 0 或 cost_price 0
- **THEN** MUST 显示 `0.00%`（不报错）

#### Scenario: 期初配额递减

- **GIVEN** 期初持仓 last_vol=1000，已买 300，已卖 200
- **WHEN** 渲染可买/可卖列
- **THEN** MUST 显示 `700 / 800`（maxBuyable=700=1000-300, maxSellable=800=1000-200）
- **AND** 系统 MUST NOT 用 cash 或 avl_vol 计算

#### Scenario: 操作列 4 按钮保留

- **GIVEN** 主表已渲染
- **WHEN** 检查操作列
- **THEN** MUST 包含：买X%（Primary）/ 卖X%（Danger）/ 配平（Warning）/ 详情（link）
- **AND** 配平按钮 MUST 沿用 `_rowBalance` + `resolveBalancePrice` 独立价格档
- **AND** 按钮 disabled/tip 逻辑沿用 `useT0TradeButtons`，与本期重构解耦

### 范围外（Non-Goals）

- 不改后端 `t0-stats/{code}` 的 `realized_pnl` 字段语义（v6 算法保留）
- 不改 `holdingsStore.getReturnRate`（浮盈% 保留，2 列共存）
- 不动 `Trade.vue` / `Dashboard.vue` 等其他视图的浮盈% / realized_pnl 消费
- 不重做抽屉（仅删除 detail drawer，task 详情抽屉保留）
- 不改 stock-code-picker / autocomplete

### 风险

| 风险 | 缓解 |
|---|---|
| 删 quota frame 后看不到账户级现金 | AppHeader / Dashboard 可查 |
| 删副行 30 天 popover | task 详情抽屉保留历史曲线入口 |
| 配平 ask1/bid1 未到 → 0 | fallback 最新价 + tooltip 标记 |
| `formatPriceAuto` 显示精度突变 | 已 unit-tested 6+ 用例 |

### 相关文件

- `client/src/lib/t0-calc.js`（新增 6 纯函数）
- `client/src/lib/t0-calc.test.js`（新增单测）
- `client/src/views/T0Trade.vue`（大重做 +200/-600）
- `client/src/utils/format.js`（复用 `formatPriceAuto`，已存在）