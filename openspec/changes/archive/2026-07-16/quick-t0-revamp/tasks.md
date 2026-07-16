# tasks.md — 2026-07-16-quick-t0-revamp

> 实施 checklist，按 3 commit 顺序排列。每个子任务粒度 2–5 分钟。

## Commit 1 — lib/t0-calc.js 纯函数层

> 范围：仅 `client/src/lib/t0-calc.js`（新增）+ `client/src/lib/t0-calc.test.js`（新增单测）
> 提交类型：`feat(lib)` 或 `feat(calc)`
> commit msg: `feat(lib): t0-calc 新增做T盈亏/敞口/期初配额/做T收益率/配平对手盘价 纯函数`

### 1.1 阅读 `client/src/lib/t0-calc.js` 现状
- 确认文件存在 + 当前导出
- 确认命名风格（snake_case 函数 / JSDoc）
- 输出：现状 + 与 useQuickT0.js 的边界（避免重复实现）

### 1.2 新增 `calcT0Pnl(stats) → number`
```js
/**
 * 做T盈亏（trader 直觉口径，不含成本基准/费用）
 * = SUM(卖出成交 vol*price) - SUM(买入成交 vol*price)
 * = stats.today_sell_amount - stats.today_buy_amount
 *
 * @param {{today_buy_amount?: number, today_sell_amount?: number}} stats
 * @returns {number} 做T盈亏（正数=盈利，负数=亏损）
 */
export function calcT0Pnl(stats) { ... }
```

### 1.3 新增 `calcExposure(row, stats) → number`
```js
/**
 * 当前敞口（持仓视角）
 * = 期初持仓 + (今日买入 - 今日卖出)
 *   > 0 → 多头敞口（已超期初，需卖）
 *   < 0 → 空头敞口（已卖超期初，需买）
 *
 * @param {{last_vol?: number}} row
 * @param {{today_buy_volume?: number, today_sell_volume?: number}} stats
 * @returns {number} 敞口（正数=多，负数=空）
 */
export function calcExposure(row, stats) { ... }
```

### 1.4 新增 `calcInitialQuota(row, stats) → {maxBuyable, maxSellable}`
```js
/**
 * 期初配额 — 可买/可卖，按 last_vol 递减已成交
 *   maxBuyable  = max(0, last_vol - today_buy_volume)
 *   maxSellable = max(0, last_vol - today_sell_volume)
 *
 * @param {{last_vol?: number}} row
 * @param {{today_buy_volume?: number, today_sell_volume?: number}} stats
 * @returns {{maxBuyable: number, maxSellable: number}}
 */
export function calcInitialQuota(row, stats) { ... }
```

### 1.5 新增 `calcT0ReturnRate(row, stats) → number`
```js
/**
 * 做T收益率
 * = calcT0Pnl(stats) / (last_vol * cost_price)
 *
 * @param {{last_vol?: number, cost_price?: number}} row
 * @param {Object} stats
 * @returns {number} 收益率（小数，0.005 = 0.5%）；last_vol 或 cost_price 为 0 → 0
 */
export function calcT0ReturnRate(row, stats) { ... }
```

### 1.6 新增 `resolveBalancePrice(row, side, quote) → {price, fallback}`
```js
/**
 * 配平对手盘价（独立于 quick 价格档）
 * = buy 敞口 → ask_prices[0] (卖1)
 * = sell 敞口 → bid_prices[0] (买1)
 *
 * @param {{stock_code?: string}} row
 * @param {'buy'|'sell'} side — 配平方向
 * @param {Object|null} quote — quote store 单条数据 {last_price, ask_prices, bid_prices, ...}
 * @returns {{price: number, fallback: boolean}} price=0 表示无价；fallback=true 表示已 fallback 到最新价
 */
export function resolveBalancePrice(row, side, quote) { ... }
```

### 1.7 复用 `formatPriceAuto` 在 utils/format.js
- 不在 t0-calc.js 写格式化（避免重复），调用方自行 format
- 在 proposal 注释里点明

### 1.8 写 `t0-calc.test.js` 单测
- 用 vitest，6+ 用例：
  1. `calcT0Pnl({today_buy_amount: 1000, today_sell_amount: 1500})` → 500
  2. `calcT0Pnl({})` → 0（无成交）
  3. `calcExposure({last_vol: 1000}, {today_buy_volume: 300, today_sell_volume: 0})` → 700（多 700 敞口）
  4. `calcInitialQuota({last_vol: 1000}, {today_buy_volume: 300, today_sell_volume: 200})` → `{maxBuyable: 700, maxSellable: 800}`
  5. `calcT0ReturnRate({last_vol: 1000, cost_price: 10}, {today_buy_amount: 1000, today_sell_amount: 1500})` → 0.05 (5%)
  6. `resolveBalancePrice({}, 'buy', {ask_prices: [11.5, ...], last_price: 10})` → `{price: 11.5, fallback: false}`

### 1.9 跑 vitest 验证
```bash
cd client && npx vitest run src/lib/t0-calc.test.js
```
预期：6+ 用例全过

### 1.10 commit.1 提交
```bash
git add client/src/lib/t0-calc.js client/src/lib/t0-calc.test.js
git commit -m "feat(lib): t0-calc 新增做T盈亏/敞口/期初配额/做T收益率/配平对手盘价 纯函数"
```

## Commit 2 — T0Trade.vue 视图重做

> 范围：仅 `client/src/views/T0Trade.vue`（大改 +200/-600）
> 提交类型：`feat(ui)` 或 `refactor(ui)`
> commit msg: `feat(ui): T0Trade 主表重构 敞口/做T盈亏/做T收益率%/期初配额 + 价格 4 位小数`

### 2.1 删除 quota frame（template 行 30-76）
- 移除 `<div class="quota-frame">` 整段
- 移除 `useT0Quota` import（孤儿）— 保留 `useT0Quota.js` 文件以备 Dashboard 复用
- 移除 `quotaAggregate / todayPnlText / todayPnlClass` computed
- 移除 quota frame 相关 CSS

### 2.2 改主表列定义（template 行 78-265）
删除：
- quota 列（可买/可卖，prop=max_buyable/max_sellable，行 144-164）

修改：
- "现价"列（行 95-101）→ 合并"涨跌"列（行 102-108）→ 单列 `label="现价(涨跌幅)"` width 140
- "今盈"列（行 111-120）→ label 改"做T盈亏"，width 100，值改 `today_sell_amount - today_buy_amount`
- "净敞口"列（行 123-132）→ 改"敞口"，值改 `calcExposure(row, t0StatsMap[row.stock_code])`
- "浮盈%"列（行 135-141）→ 保留（不变）
- 新增"做T收益率%"列（width 100）— `calcT0ReturnRate(row, stats)`
- 新增"可买/可卖"单列 width 110 — `calcInitialQuota(row, stats)` 显示 `700 / 800`

### 2.3 删除副行（template 行 201-264）
- 移除 `<el-table-column type="expand">`
- 移除 history30dMap / ensureHistory30d 相关 script + state

### 2.4 删除抽屉（template 行 300-391）
- 移除 `<el-drawer v-model="drawerVisible">`（含 chart svg + stats）
- 移除 drawer 相关 state（drawerVisible / drawerLoading / drawerStats / drawerHistory / drawerDays / drawerAggregate）
- 移除 onOpenDrawer / onDrawerChangeDays / drawerCumHistory / drawerChartW/H/Pad 等
- 移除 useT0DrawerChartGeometry import

### 2.5 删除底部 30 日曲线（template 行 267-297）
- 移除 `<div class="bottom-chart">` + svg
- 移除 historyDays / historyData / loadT0History / cumHistory / bottomChartW/H/Pad / useT0ChartGeometry

### 2.6 配平按钮逻辑改
- 在 `_rowBalance` 中追加 `quote` 入参
- 新增 `resolveBalancePrice(row, side, quote)` 调用
- `onQuickBalance` 中改 `r.price = resolveBalancePrice(row, bal.side, quoteStore.get(row.stock_code)).price`
- tooltip 改 `用卖1/买1价配平，备选最新价`

### 2.7 价格列格式化统一
- 把所有 `formatPrice(...)` 改为 `formatPriceAuto(...)`
- 包括：现价、敞口（不涉及）、做T盈亏、成本、cost_price 副行（已删副行）、drawer stats（已删 drawer）

### 2.8 script setup 清理
- 移除 unused imports：`useT0DrawerChartGeometry` / `useT0Quota` / `quotaLevel` / `ElMessageBox`（保留，可能仍用）
- 移除 unused refs：`quotaAggregate` / `drawerVisible` / `drawerLoading` / `drawerStats` / `drawerHistory` / `drawerDays` / `drawerAggregate` / `historyDays` / `historyData` / `history30dMap` / `selectedRowCode`（保留光标导航）/`drawerSize` / `drawerCumHistory` / `drawerChartW/H/Pad` / `bottomCumHistory` 等

### 2.9 CSS 清理
- 移除 quota-frame 相关样式
- 移除 quota-cell / quota-low / quota-mid / quota-high 等
- 移除 sub-row / sub-item / sub-popover 相关样式
- 移除 drawer 相关样式
- 移除 bottom-chart 相关样式
- 保留 op-col / op-btn-*（操作列）

### 2.10 浏览器实测
```bash
python3 scripts/evctl.py restart  # 重启 backend（如有改动，但本次后端 0 改动，可跳）
```
操作：
1. 浏览器 navigate `/t0-trade`
2. 登录 admin/admin123
3. 检查主表列数 = 11
4. 检查 4 列值：敞口/做T盈亏/做T收益率%/可买可卖
5. 检查现价列显示 "10.50 (+0.50%)" 格式（合并后）
6. vision 截图复检布局
7. 测配平：人工制造敞口 → 点配平 → 验证用 ask1/bid1 价

### 2.11 commit.2 提交
```bash
git add client/src/views/T0Trade.vue
git commit -m "feat(ui): T0Trade 主表重构 敞口/做T盈亏/做T收益率%/期初配额 + 价格 4 位小数"
```

## Commit 3 — OpenSpec spec + archive

> 范围：`openspec/changes/2026-07-16-quick-t0-revamp/` → archive + 新增 REQ-FE-220 到 specs/frontend/spec.md
> 提交类型：`docs(spec)`
> commit msg: `docs(spec): REQ-FE-220 T0Trade 主表重构契约`

### 3.1 合并 spec-deltas/frontend.md 到 specs/frontend/spec.md
- 在"REQ-FE-210 之后"插入 "REQ-FE-220"
- 描述：11 列定义 / 做T盈亏公式 / 配平对手盘价 / 期初配额 / 做T收益率 / 价格 4 位小数

### 3.2 git mv 归档
```bash
mkdir -p openspec/changes/archive
git mv openspec/changes/2026-07-16-quick-t0-revamp openspec/changes/archive/
git status  # 验证 100% rename
```

### 3.3 commit.3 提交 + push
```bash
git add openspec/
git commit -m "docs(spec): REQ-FE-220 T0Trade 主表重构契约 + archive 2026-07-16-quick-t0-revamp"
git push origin master
```

### 3.4 双 hash 验证
```bash
git log -1  # local
git log -1 origin/master  # remote 一致
```

## 总任务数

| 段 | 子任务数 |
|---|---|
| Commit 1 (lib) | 10 |
| Commit 2 (ui) | 11 |
| Commit 3 (spec + archive) | 4 |
| **总计** | **25** |