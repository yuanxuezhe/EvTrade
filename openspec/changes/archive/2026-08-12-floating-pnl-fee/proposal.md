# 2026-08-12-floating-pnl-fee — 浮动盈亏扣除费用（对齐当日盈亏）

## Why

用户需求（2026-08-12）：「浮动盈亏没有考虑佣金，按当日盈亏的佣金计算公式计算」。

当前前端 `getProfit`（`stores/holdings_market.js`）计算浮动盈亏 = `(现价 − 成本) × 量`，
**不含任何交易费用**。而「当日盈亏」（`lib/t0-calc.js:calcDayPnl` + 后端 `aggregators.py:123`）
已扣费：`day_fee = 买佣金(今日买入额) + 卖佣金(今日卖出额) + 印花税(今日卖出额)`（费率来自
sysconfig，`calc_commission_and_tax`）。两口径并排展示时，浮动盈亏虚高、当日盈亏已扣费，显示不一致。

## What Changes

浮动盈亏公式从裸价差改为扣费版，**费用直接用当日盈亏的 day_fee**：

```
浮动盈亏 = (现价 − 成本) × 量 − 当日费用 day_fee
```

- **day_fee = 当日实际买卖成交金额的费用**（用户 2026-08-12 最终口径：「费用只需要考虑当日
  买卖成交金额」）。由后端 t0-exposure 按 `aggregators.py:123` 聚合，浮动盈亏与当日盈亏扣
  **同一 day_fee** → 两者费用完全一致，且符合 REQ-FE-533「前端不做二次费率逻辑」。
- **演进**（复检修正史）：
  1. 初版：按整仓名义额自算 `买佣金 + 卖佣金 + 印花税` → 对「今日买入、持有未卖」仓位比当日
     盈亏**多一倍**（159530.SZ 实测：当日扣 1.00，浮动扣 2.01，卖佣金被预扣）。
  2. 修正 v2：只扣 `买佣金(成本×量)` → 仍非"当日实际成交"口径。
  3. **定稿 v3**：直接扣后端 day_fee（当日实际买卖成交金额），与当日盈亏费用 100% 一致。

### 纯函数（`lib/t0-calc.js` 新增）

```js
export function calcFloatingPnl({ price, cost, vol, day_fee = 0 })
  // → number | null：(现价−成本)×量 − day_fee；无 day_fee → 0 退化裸价差；
  //   vol=0 → 0；行情缺失 → null；结果 round 2
```

（`calcCommissionAndTax` 前端镜像实现已移除 — 费用权威在后端 day_fee，前端不再自算佣金。）

### 接线

- `useT0DayPnl.js`：新增 `getDayFee(position)`（t0-exposure 聚合 map 读 day_fee，与 `getDayPnl`
  同一数据源）。
- `holdings_daypnl.js`：`recomputeAll` 在写 `p.day_pnl` 时同步写 `p.day_fee`（供浮动盈亏扣费，
  随当日盈亏一起刷新，无额外轮询）。
- `stores/holdings_market.js`：`getProfit` 改调 `calcFloatingPnl`（入参现价/成本/量/`p.day_fee`），
  `getReturnRate` 自动继承（它调 getProfit）。
- 撤销初版的 feeConfig 接线：`holdings.js` 移除 `feeConfig` ref + `loadFeeConfig()` + `feeConfigApi`
  注入，`createMarketComputeds` 保持原 3 参。

### 不做的事

- ❌ 不改后端（day_fee 已由 t0-exposure 聚合，费率权威在 sysconfig）
- ❌ 前端不自算佣金 / 不拉 `/fee-config`（REQ-FE-533 前端不做二次费率逻辑）
- ❌ 不新增 store / 不拆 facade（沿用 holdings.js 单 facade + t0-calc 纯函数层）
- ❌ 不引入轮询（day_fee 随当日盈亏 recompute 刷新，行情推送驱动）

## 时序

```
t0-exposure 拉取 → useT0DayPnl._map (buy/sell/day_fee)
  → holdings_daypnl.recomputeAll 写 positions[].day_fee (quote.tick/positions/成交事件驱动)
  → getProfit → calcFloatingPnl(现价, 成本, 量, p.day_fee) → HoldingsPanel 浮动盈亏列
```

## 改动文件清单

| 层 | 文件 | 改动 |
|---|---|---|
| 前端 | `client/src/lib/t0-calc.js` | 新增 `calcFloatingPnl({price, cost, vol, day_fee})`；移除 `calcCommissionAndTax` |
| 前端 | `client/src/composables/useT0DayPnl.js` | 新增 `getDayFee(position)` |
| 前端 | `client/src/stores/holdings_daypnl.js` | `recomputeAll` 同步写 `p.day_fee` |
| 前端 | `client/src/stores/holdings_market.js` | `getProfit` 扣 `p.day_fee`；`createMarketComputeds` 保持 3 参 |
| 前端 | `client/src/stores/holdings.js` | 移除 feeConfig 接线（ref/loadFeeConfig/import） |
| 测试 | `tests/client/lib/t0-calc.test.js` | `calcFloatingPnl` 按 day_fee 用例；移除 `calcCommissionAndTax` 用例 |
| 知识库 | `openspec/specs/frontend/spec.md` | 新增 REQ-FE 浮动盈亏扣费（day_fee 口径）；修正 REQ-FE-533 `day_fee` 误述「无印花税」→「含卖出印花税」 |

## 关联

- 上游：`REQ-FE-533`（当日盈亏口径，2026-08-12）；`aggregators.py:123`（day_fee 构成）；
  `fees.py:calc_commission_and_tax`（后端费率计算权威）；`data-model spec cost_price scale`（成本精度）
