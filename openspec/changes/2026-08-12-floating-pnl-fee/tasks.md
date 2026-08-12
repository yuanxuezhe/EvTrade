# Tasks — 浮动盈亏扣除佣金（对齐当日盈亏公式）

> 先知识库后代码。用户确认口径「买卖都扣（对齐当日盈亏）」= 买佣金 + 卖佣金 + 印花税(卖出)。
> 改动分 3 commit 便于 review/回滚。

## 1 — 知识库

- [ ] 1.1 创建 change proposal（proposal.md）
- [ ] 1.2 主 spec 落地：`openspec/specs/frontend/spec.md`
      - [ ] 新增 REQ-FE：浮动盈亏 getProfit 扣费口径（公式 + 费率来源 + 降级）
      - [ ] 修正 REQ-FE-533 day_fee 误述「无印花税」→「买佣金 + 卖佣金 + 印花税(卖出)」（对齐 aggregators.py:123）
- [ ] 1.3 commit: `docs(spec): 浮动盈亏按当日盈亏公式扣佣金 (floating-pnl-fee)`

## 2 — 前端实现

- [ ] 2.1 `lib/t0-calc.js`：新增 `calcCommissionAndTax(amount, feeCfg, direction)`（镜像 fees.py）+ `calcFloatingPnl({price, cost, vol, fee_cfg})`
- [ ] 2.2 `stores/holdings_market.js`：`getProfit` 改调 `calcFloatingPnl`（签名加 feeConfig 注入）
- [ ] 2.3 `stores/holdings.js`：`feeConfig` ref + `loadFeeConfig()`（bootstrap fire-and-forget）+ 注入 createMarketComputeds
- [ ] 2.4 commit: `feat(client): 浮动盈亏扣佣金, 对齐当日盈亏公式 (floating-pnl-fee)`

## 3 — 测试

- [ ] 3.1 `tests/client/lib/t0-calc.test.js`：`calcCommissionAndTax` / `calcFloatingPnl` 用例（镜像 calcDayPnl 风格, toBeCloseTo）
- [ ] 3.2 验证：vitest 新用例全绿 + t0-calc.test.js 其余用例无 regression
