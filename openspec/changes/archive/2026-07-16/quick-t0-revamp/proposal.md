# 2026-07-16-quick-t0-revamp — 快速做T 页重构

## Why

用户反馈 `client/src/views/T0Trade.vue` 界面设计不合理，三类问题：

1. **做T盈亏口径不一致** — 后端 `t0-stats/{code}` 用 v6 算法 `(avg_sell - cost_basis) * sell_vol - commission - stamp_tax`（基于持仓成本基准 + 费用），不符合做T人最直觉的"卖 - 买"口径（`SUM(卖出vol*price) - SUM(买入vol*price)`）。Trade.vue / Dashboard.vue 等仍在消费旧的 `realized_pnl`，新做T盈亏应作为新字段独立提供。

2. **配平价格档语义错位** — 现有配平按钮沿用 quick 价格档（last/market/bidask），但做T人配平时需要的是"对手盘价"（买敞口用卖1、卖敞口用买1），与新开仓"按市价/最新价"语义不同。沿用同一档造成 trader 配平时无法快速表达意图。

3. **可买可卖口径错** — 现有 `useT0Quota.rowQuota` 的 `maxBuyable = floor(cash/price/100)*100`（按可用资金算），`maxSellable = avl_vol`。但做T场景的"敞口"是基于 **期初持仓**（`last_vol`）的：今天无论买多少都受限于"本来有多少"，今天无论卖多少也不能卖超"本来有多少"。当前实现把"按资金能买多少"和"按持仓能卖多少"硬塞进做T 场景，语义不对。

4. **价格展示精度硬卡 2 位** — `formatPrice(x, 2)` 把所有价格砍成 2 位小数，0.0039 之类的可转债/低价股场景直接显示 "0.00"，丢失关键信号。做T 人对 1-2 分钱敏感，需要最多 4 位小数。

5. **布局信息冗余** — 主表 quota frame 5 pill + quota 列 + 净敞口列 + 副行 30 天 popover + 抽屉 + 底部 30 日曲线，多处表达同一组数字。删除冗余后主表核心列一目了然。

## What Changes

### 1. 新增 lib 纯函数（`client/src/lib/t0-calc.js`）

```javascript
/**
 * 做T盈亏（trader 直觉口径，不含成本基准/费用）
 * = SUM(卖出成交 vol * price) - SUM(买入成交 vol * price)
 */
calcT0Pnl(stats) → number

/**
 * 当前敞口（持仓视角）
 * = 期初持仓 + (今日买入 - 今日卖出)
 *   > 0 → 多头敞口（已超期初），需卖
 *   < 0 → 空头敞口（已卖超期初），需买
 */
calcExposure(row, stats) → number

/**
 * 期初配额 — 可买/可卖，按 last_vol 递减已成交
 * maxBuyable  = last_vol - today_buy_volume  (含买敞口)
 * maxSellable = last_vol - today_sell_volume (含卖敞口)
 */
calcInitialQuota(row, stats) → { maxBuyable, maxSellable }

/**
 * 做T收益率
 * = calcT0Pnl / (last_vol * cost_price)
 */
calcT0ReturnRate(row, stats) → number

/**
 * 配平对手盘价
 * = buy 敞口 → ask1 (卖1价)
 * = sell 敞口 → bid1 (买1价)
 * 取不到 → fallback 最新价 + 返回 { fallback: true }
 */
resolveBalancePrice(row, side, quote) → { price, fallback }

/**
 * 4 位小数智能格式化（去尾 0）
 * 复用 utils/format.formatPriceAuto
 */
```

### 2. T0Trade.vue 大重做

**删除**：
- quota frame 5 pill（账户级信息从 AppHeader 或其他页查看）
- quota 列（可买/可卖改为 row 内联于操作列或专列）
- 净敞口列（合并进"敞口"列）
- 副行（30 天 popover + 胜率）— 信息冗余
- 抽屉（详情 + 历史曲线 + aggregate）— 保留 task 详情抽屉作为唯一明细入口
- 底部 30 日曲线（重复信息）

**主表 11 列**（顺序）：
1. 代码（width 100）
2. 名称（width 100）
3. 期初（width 80，= last_vol，整百对齐）
4. 现价(涨跌幅)（width 140，合并为单列）
5. 已买（width 80，today_buy_volume）
6. 已卖（width 80，today_sell_volume）
7. 敞口（width 80，= 期初 + 已买 - 已卖，正数红 / 负数绿 / 0 灰）
8. 做T盈亏（width 100，= sum(sell) - sum(buy)）
9. 做T收益率%（width 100，= 做T盈亏 / (last_vol * cost)）
10. 可买/可卖（width 100，按 last_vol 递减）
11. 操作（width 320，fixed right：4 按钮 — 买X% / 卖X% / 配平 / 详情入口）

**配平按钮逻辑**：
- 独立价格档 `balancePriceType='askbid'`，与 quick 价格档解耦
- 买敞口 → 取 `ask_prices[0]`，fallback 最新价
- 卖敞口 → 取 `bid_prices[0]`，fallback 最新价
- tooltip 显示"用卖1价/买1价 配平"

**价格小数位**：
- 主表所有价格列 → `formatPriceAuto`（最多 4 位小数去尾 0）
- 操作列 tooltip → `formatPriceAuto`
- 期初/已买/已卖 → `formatNumber` 整百对齐（不变）

**做T盈亏单元格**：
- = `stats.today_sell_amount - stats.today_buy_amount`
- 颜色：> 0 红（A 股红涨）、< 0 绿、= 0 灰
- 0 成交 → 显示 `--` 灰色

**做T收益率%单元格**：
- = `(stats.today_sell_amount - stats.today_buy_amount) / (row.last_vol * row.cost_price)` （单位对齐，金额/金额）
- `last_vol` 或 `cost_price` 为 0 → 0%
- `> 0` 红、`< 0` 绿、`= 0` 灰

### 3. OpenSpec 新增 REQ

- `REQ-FE-220`: T0Trade 主表重构（敞口/做T盈亏/做T收益率%/可买可卖基于期初持仓）

## Impact

### 影响面

| 模块 | 影响 | 备注 |
|---|---|---|
| `client/src/lib/t0-calc.js` | **新增 6 纯函数** | 纯函数层，可单测 |
| `client/src/views/T0Trade.vue` | **大重做**，从 1176 行降到 ~600 行 | 删 quota frame/列/副行/抽屉/底部曲线；改 11 列；改配平逻辑；价格全部 formatPriceAuto |
| `client/src/composables/useT0Quota.js` | **保留但不再用于主表**（quota frame 移除后变孤儿） | 删除或保留作他用（建议保留，Dashboard 可能复用） |
| `client/src/composables/useT0TradeButtons.js` | **保留**（按钮 disabled/tip 仍用） | 配平逻辑可能要微调以配合新 calcExposure |
| `client/src/composables/useQuickT0.js` | **保留** | calcBuyQty/calcSellQty 仍用，不改 |
| 后端 | **0 改动** | Q2=B 用 t0StatsMap 已有字段，不动后端 |

### 兼容性

- **后端 `realized_pnl` 字段语义不变**（仍按 v6 算法）— Trade.vue / Dashboard.vue 等其他视图仍可消费
- **`useT0Quota` 保留** — Dashboard / 未来 reuse
- **t0StatsMap 数据源不变** — 30s TTL 缓存，前端 `loadAllT0Stats()` 仍调用
- **配平价格档独立** — 与 quick 价格档解耦，UI 顶部不再有全局配平价格档选择

## Non-Goals（不在本次范围）

1. 不改后端 `t0-stats/{code}` 的 `realized_pnl` 字段语义（Q2=B 已规避）
2. 不改 `holdingsStore.getReturnRate`（Q5=B 保留旧浮盈%）
3. 不改 Trade.vue / Dashboard.vue 的浮盈% 显示
4. 不重做抽屉 — 抽屉保留 task 详情入口（其他功能删除）
5. 不改 OpenSpec 现有 REQ（REQ-FE-200/210/510）— 仅新增 REQ-FE-220
6. 不动 4 处 `Query(regex=)` → `Query(pattern=)` 迁移（v53 commit 已单独修 1 处）
7. 不重做 stock-code-picker / autocomplete（已有）

## Risk

| 风险 | 级别 | 缓解 |
|---|---|---|
| 删 quota frame 后 trader 看不到账户级现金/冻结/T+0 可用 | 中 | AppHeader 顶部已有总览；Dashboard 可查；任务弹窗已聚合 |
| 删副行 30 天 popover → 丢历史 hover 入口 | 低 | task 详情抽屉保留历史曲线入口 |
| 配平 ask1/bid1 行情未到 → 0 | 中 | 取不到时 fallback 最新价 + tooltip 标记 fallback |
| 做T盈亏口径变化 → 其他视图如再读 `realized_pnl` 会以为已切换 | 低 | 字段名分离（前端用新计算式，后端字段不动） |
| `formatPriceAuto` 在某些场景显示 `.` 开头 | 低 | 已有 fallback：0 → "0" |
| 改主表列数 → 仪表盘 T0 卡片如果也读这些列需要更新 | 低 | 仪表盘读 holdings store / t0StatsMap，不读 T0Trade 局部 |
| 删抽屉后丢失"详情"快捷入口 | 中 | 仍保留"详情"链接按钮，跳到 task 详情抽屉 |
| 可买可卖基于 last_vol → 用户已部分成交后回看易误读 | 低 | tooltip 明示"基于期初持仓" |