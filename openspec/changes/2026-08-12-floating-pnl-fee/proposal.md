# 2026-08-12-floating-pnl-fee — 浮动盈亏扣除佣金（对齐当日盈亏公式）

## Why

用户需求（2026-08-12）：「浮动盈亏没有考虑佣金，按当日盈亏的佣金计算公式计算」。

当前前端 `getProfit`（`stores/holdings_market.js`）计算浮动盈亏 = `(现价 − 成本) × 量`，
**不含任何交易费用**。而「当日盈亏」（`lib/t0-calc.js:calcDayPnl` + 后端 `aggregators.py:123`）
已按费率扣费：`day_fee = 买佣金 + 卖佣金 + 印花税（卖出）`（费率来自 sysconfig，
`calc_commission_and_tax`）。两口径并排展示时，浮动盈亏虚高、当日盈亏已扣费，显示不一致。

用户确认口径：**买卖都扣（对齐当日盈亏）**。
2026-08-12 复检：159530.SZ 实测浮动盈亏费用比当日盈亏**多一倍** → 修正为**只扣买佣金**（见下）。

## What Changes

浮动盈亏公式从裸价差改为扣费版：

```
浮动盈亏 = (现价 − 成本) × 量 − 买佣金（成本 × 量 × commission_rate，round 2，min_commission 兜底）
```

**只扣买佣金，不预扣卖佣金/印花税**。根因：当日盈亏 `day_fee`（`aggregators.py:123`）
只按**今日实际成交**计费（买佣金(今日买入额) + 卖佣金(今日卖出额) + 印花税）。对「今日买入、
持有未卖」仓位，当日盈亏只含买佣金；浮动盈亏若把整仓名义额的卖佣金+印花税也扣掉，会
**比当日盈亏多一倍**（159530.SZ，万1费率：当日扣 1.00，浮动扣 2.01）。持仓未实现部分不产生
卖出费用 → 只扣已发生的买入佣金，使两者在「今日买入持有」场景完全相等。

镜像后端 `fees.py:calc_commission_and_tax` 语义，前端在纯函数层实现，避免重复费率逻辑散落。

### 费率来源

- 前端**首次启动拉一次** `GET /fee-config`（`api/admin.js:feeConfigApi.get()` →
  `FeeConfigOut {commission_rate, stamp_tax_rate, slippage, min_commission, updated_at}`），
  存 holdings store 的 `feeConfig` ref，注入 `createMarketComputeds`。
- 拉取失败 / 尚未返回 → `feeConfig = null` → 浮动盈亏**退化为裸价差**（graceful，不阻断持仓加载）。

### 纯函数（`lib/t0-calc.js` 新增）

```js
export function calcCommissionAndTax(amount, { commission_rate, min_commission = 0, stamp_tax_rate = 0 } = {}, direction)
  // → { commission, stamp_tax }：镜像 fees.py:calc_commission_and_tax（round 2，min 兜底，印花仅卖出）

export function calcFloatingPnl({ price, cost, vol, fee_cfg })
  // → number | null：扣费浮动盈亏；无 fee_cfg → 裸价差；vol=0 → 0；行情缺失 → null
```

### 接线

- `stores/holdings.js`：新增 `feeConfig = ref(null)` + `loadFeeConfig()`（bootstrap 内 fire-and-forget），
  `createMarketComputeds` 注入第 4 参。
- `stores/holdings_market.js`：`getProfit` 改调 `calcFloatingPnl`（入参现价/成本/量/feeConfig），
  `getReturnRate` 自动继承（它调 getProfit）。

### 不做的事

- ❌ 不改后端（费率接口已存在；当日盈亏 day_fee 仍由后端聚合，本 change 只动前端浮动盈亏口径）
- ❌ 不新增 store / 不拆 facade（沿用 holdings.js 单 facade + t0-calc 纯函数层）
- ❌ 不引入轮询（费率低频，仅启动拉一次；刷新数据沿用既有 refreshAll 不动费率）

## 时序

```
GET /fee-config (启动一次) → feeConfig ref → getProfit(fee_cfg) → calcFloatingPnl 扣费
行情 tick → quoteStore → HoldingsPanel 浮动盈亏列实时刷新（含扣费）
```

## 改动文件清单

| 层 | 文件 | 改动 |
|---|---|---|
| 前端 | `client/src/lib/t0-calc.js` | 新增 `calcCommissionAndTax` / `calcFloatingPnl` 纯函数 |
| 前端 | `client/src/stores/holdings.js` | `feeConfig` ref + `loadFeeConfig()`，注入 `createMarketComputeds` |
| 前端 | `client/src/stores/holdings_market.js` | `getProfit` 改调 `calcFloatingPnl`（签名加 feeConfig） |
| 测试 | `tests/client/lib/t0-calc.test.js` | `calcCommissionAndTax` / `calcFloatingPnl` 用例（镜像 calcDayPnl 风格） |
| 知识库 | `openspec/specs/frontend/spec.md` | 新增 REQ-FE 浮动盈亏扣费；修正 REQ-FE-533 `day_fee` 误述「无印花税」→「含卖出印花税」 |

## 关联

- 上游：`REQ-FE-533`（当日盈亏口径，2026-08-12）；`fees.py:calc_commission_and_tax`；`aggregators.py:123`（day_fee 构成）；`data-model spec cost_price scale`（成本精度）
