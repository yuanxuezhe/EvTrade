# Tasks — 浮动盈亏扣除费用（对齐当日盈亏）

> 先知识库后代码。最终口径（2026-08-12 用户确认）：**费用只考虑当日实际买卖成交金额** =
> 后端 day_fee（t0-exposure 聚合）。改动分 commit 便于 review/回滚。

## 0 — 复检修正史（159530.SZ 多扣一倍 → 定稿 day_fee）

- [x] 0.1 根因 v1：浮动盈亏扣买+卖佣金 vs 当日盈亏只扣今日实际成交费用 → 未卖仓位卖佣金被预扣，费用≈2×
- [x] 0.2 修正 v2：`calcFloatingPnl` 只扣买佣金(成本×量)（commit 121a485）
- [x] 0.3 **定稿 v3**：费用直接用后端 day_fee（当日实际买卖成交金额），移除前端自算佣金/feeConfig
- [x] 0.4 commit: `fix(client): 浮动盈亏费用直接用后端 day_fee, 前端不再自算佣金`

## 1 — 知识库

- [x] 1.1 创建 change proposal（proposal.md）
- [x] 1.2 主 spec 落地：`openspec/specs/frontend/spec.md`
      - [x] 新增 REQ-FE：浮动盈亏 getProfit 扣费口径（公式 + 费率来源 + 降级）
      - [x] 修正 REQ-FE-533 day_fee 误述「无印花税」→「买佣金 + 卖佣金 + 印花税(卖出)」（对齐 aggregators.py:123）
- [x] 1.3 commit: `docs(spec): 浮动盈亏按当日盈亏公式扣佣金 (floating-pnl-fee)`

## 2 — 前端实现（定稿 v3: day_fee 口径）

- [x] 2.1 `lib/t0-calc.js`：新增 `calcFloatingPnl({price, cost, vol, day_fee})`；移除 `calcCommissionAndTax`
- [x] 2.2 `useT0DayPnl.js`：新增 `getDayFee(position)`（t0-exposure map 读 day_fee）
- [x] 2.3 `holdings_daypnl.js`：`recomputeAll` 同步写 `p.day_fee`
- [x] 2.4 `holdings_market.js`：`getProfit` 扣 `p.day_fee`；`createMarketComputeds` 保持原 3 参
- [x] 2.5 `holdings.js`：移除 feeConfig 接线（ref/loadFeeConfig/feeConfigApi import）
- [x] 2.6 commit: `fix(client): 浮动盈亏费用直接用后端 day_fee, 前端不再自算佣金`

## 3 — 测试

- [x] 3.1 `tests/client/lib/t0-calc.test.js`：`calcFloatingPnl` 按 day_fee 用例（含 day_fee 缺失/无效降级）；移除 `calcCommissionAndTax` 用例
- [x] 3.2 验证：t0-calc + daypnl_livepush 全绿（45/45）+ holdings store 3 失败为预存（stash 对照一致, 非 regression）
