# Tasks — 浮动盈亏扣除佣金（对齐当日盈亏公式）

> 先知识库后代码。用户确认口径「买卖都扣（对齐当日盈亏）」；2026-08-12 复检修正：
> 只扣买佣金（当日盈亏 day_fee 只算今日实际成交费用，未卖出持仓不预扣卖佣金/印花税，
> 否则比当日盈亏多一倍）。改动分 commit 便于 review/回滚。

## 0 — 复检修正（159530.SZ 多扣一倍）

- [x] 0.1 根因：浮动盈亏扣买+卖佣金 vs 当日盈亏只扣今日实际成交费用 → 未卖仓位卖佣金被预扣，费用≈2×
- [x] 0.2 修正：`calcFloatingPnl` 只扣买佣金(成本×量)；spec/proposal 同步修正公式
- [x] 0.3 commit: `fix(client): 浮动盈亏只扣买佣金, 不再预扣卖佣金/印花税`

## 1 — 知识库

- [x] 1.1 创建 change proposal（proposal.md）
- [x] 1.2 主 spec 落地：`openspec/specs/frontend/spec.md`
      - [x] 新增 REQ-FE：浮动盈亏 getProfit 扣费口径（公式 + 费率来源 + 降级）
      - [x] 修正 REQ-FE-533 day_fee 误述「无印花税」→「买佣金 + 卖佣金 + 印花税(卖出)」（对齐 aggregators.py:123）
- [x] 1.3 commit: `docs(spec): 浮动盈亏按当日盈亏公式扣佣金 (floating-pnl-fee)`

## 2 — 前端实现

- [x] 2.1 `lib/t0-calc.js`：新增 `calcCommissionAndTax(amount, feeCfg, direction)`（镜像 fees.py）+ `calcFloatingPnl({price, cost, vol, fee_cfg})`
- [x] 2.2 `stores/holdings_market.js`：`getProfit` 改调 `calcFloatingPnl`（签名加 feeConfig 注入）
- [x] 2.3 `stores/holdings.js`：`feeConfig` ref + `loadFeeConfig()`（bootstrap fire-and-forget）+ 注入 createMarketComputeds
- [x] 2.4 commit: `feat(client): 浮动盈亏扣佣金, 对齐当日盈亏公式 (floating-pnl-fee)`

## 3 — 测试

- [x] 3.1 `tests/client/lib/t0-calc.test.js`：`calcCommissionAndTax` / `calcFloatingPnl` 用例（镜像 calcDayPnl 风格, toBeCloseTo）
- [x] 3.2 验证：vitest 新用例全绿（50/50）+ holdings store 3 失败为预存（stash 对照一致, 非 regression）
