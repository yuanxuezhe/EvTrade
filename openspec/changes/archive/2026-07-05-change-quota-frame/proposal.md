## Why

`/t0-trade` 主表行内 4 按钮 (买% / 卖% / 配平 / 详情) 已有，但 trader 在下笔前缺少**账户级 quota 概览**——必须看抽屉才知道"现金余额 / 冻结资金 / T+0 可用 / 今日已盈亏"，没法横向对比各持仓 quota 余量。多标的轮动快节奏下单场景下，这层缺失导致 trader 频繁误判资金/持仓余量，broker 拒收后才反馈。

目的：在 T0Trade 顶部加 **quota frame** (一行 4-5 个 metric pill)，并在每行加 quota 余量提示列，让 trader 下单前一眼看清"还能买多少 / 还能卖多少 / 今日盈亏 / 现金余量"。

## What Changes

- **(新 quota frame)** T0Trade 顶部新增 `<quota-frame>` 横排 metric pills:
  - 现金余量 (cash - frozen_cash)
  - 冻结资金 (frozen_cash，揭示在途买单占用)
  - T+0 可用持仓 (sum(avl_vol)) — 揭示可立即卖的持仓
  - 今日已盈亏 (sum(t0Stats.realized_pnl)) — 跨持仓聚合
  - 持仓市值 (market_value)
- **(行内 quota 列)** 主表加 `可买/可卖` 2 列:
  - `可买` = floor(cash / price / 100) * 100，按 quoteStore.getLastPrice(row) 估算最大可买股数
  - `可卖` = row.avl_vol（直接读 store）
  - 颜色提示：≥1000 绿 / 100-1000 橙 / <100 红 / =0 灰
- **(新 composable)** `useT0Quota.js`（~80 行纯函数 + reactive wrapper）：
  - `aggregateQuota(asset, positions, t0StatsMap)` → `{ cashAvail, frozenCash, t0AvailVol, todayPnl, marketValue }`
  - `rowQuota(row, cash, price)` → `{ maxBuyable, maxSellable, maxBuyableLabel }`
- **(改 T0Trade.vue)** 接入 quota frame + 配额列；不破坏现有排序/快捷键/抽屉
- **(新单测)** `client/src/composables/useT0Quota.test.js`（~15 用例）：aggregate + row + 边界

**BREAKING**:
- 无 API/RPC/数据契约变更，纯前端展示层
- 无 store schema 变更（仅读 cachedAsset / positions / t0StatsMap）

## Capabilities

### New Capabilities
- `t0-quota-frame`: T0Trade 顶部 quota 概览 frame + 行内 quota 余量列 + useT0Quota composable

### Modified Capabilities
- `frontend`: T0Trade 视图层加 quota frame + 行内配额列（新增 spec 场景）

## Impact

- 受影响文件（单 change 多 commit 拆分）：
  - `client/src/composables/useT0Quota.js`（新，~80 行）
  - `client/src/views/T0Trade.vue`（改：加 quota-frame + 配额列）
  - `client/tests/views/T0Trade.test.js`（追加 8 quota 用例）
  - `client/tests/composables/useT0Quota.test.js`（新，~15 用例）
  - `openspec/specs/frontend/spec.md`（MODIFIED REQ-FE-200 新增 quota 场景）
  - `openspec/specs/t0-quota-frame/spec.md`（新 capability）
- 不动：ws push / RPC / broker 协议 / backend / store schema
- 单测覆盖：`useT0Quota.test.js` 15 + T0Trade.test.js 8 + 现有 19 = 42 用例
- 集成验证：`npm test -- --run`（应 250+23=273 全过）