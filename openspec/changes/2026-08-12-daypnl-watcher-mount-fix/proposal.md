# 2026-08-12-daypnl-watcher-mount-fix — 刷新后「当日盈亏」列恒为空

## Why

用户反馈（2026-08-12）：「有点问题，浮动盈亏计算了，为什么当日盈亏没有算出来数据」；修复 + 浏览器刷新后仍「当日盈亏还是没数据，浮动盈亏都能正常显示」。

排查结果：**当日盈亏 recompute 机制在「刷新 + token 已持久化」场景下从未启动**，且 live push 丢失了 `prev_close`（昨收）。两处独立缺陷叠加导致列恒空：

### 缺陷 1（根因）：`_startWatchers()` 在已登录刷新时从未执行

- `App.vue` 挂载时（`onMounted`）只调 `holdingsStore.bootstrap()`，**不调 `_startWatchers()`**（`client/src/App.vue:83`）。
- `_startWatchers()` 的**唯一**调用点在 auth watch（`App.vue:101`），而该 watch **无 `immediate: true`**。
- v119 起 token 持久化（`tokenStorage` 走 localStorage）→ 刷新后 auth store 在**同步创建时**就恢复 `token` + `user` → `isAuthenticated` 初始即为 `true` → 非 immediate 的 auth watch **不会触发** → `_startWatchers()`（含 `startDayPnl()` 的 quote.tick 重算 watcher）**永不执行**。
- 结果：`positions[].day_pnl` 永远不被写入 → 当日盈亏列空。**浮动盈亏正常**是因为 `HoldingsPanel` 的 `getProfit()` 走 `quoteTickTrigger`（`quoteStore.size`），完全不依赖 holdings store 的 recompute 机制（`HoldingsPanel.vue:157,173-176`）。

### 缺陷 2：live push 丢失 `prev_close`

- 后端 `_parse_tick` 每笔构造 23 字段 `snapshot`（含 `prev_close`）并随 tick 广播（`quote_consumer.py:195-214,242-244`），但前端 `ws_dispatch._onQuote` 与 `holdings_push.applyQuote` 转发 `quoteStore.update()` 时**丢弃 `snapshot`** → quote store 只有 `last_price`、`prev_close` 缺失 → `calcDayPnl`（`last_price`/`prev_close` 任一无效 → null）算不出。
- subscribe_ack / REST `/quote/snapshots` 路径已带 `prev_close`（`repo_to_dict`），能覆盖大多数标的；但 live-push-only 的低频新代码若只走推送，仍缺昨收。

## What Changes

### 前端 `App.vue` — 挂载即启动 watcher（修根因）

`onMounted` 的 `if (authStore.isAuthenticated)` 分支，在 `bootstrap()` 前补 `holdingsStore._startWatchers()`：

- 覆盖「刷新后 token 已持久化 → isAuthenticated 初始即 true → auth watch 不触发」场景
- `_startWatchers()` 幂等（`holdings.js` `if (_unwatch) return`），与 auth watch 的登录路径叠加无副作用
- 登出/重登仍由 auth watch 正常启停

### 前端 quote 推送 — 转发 snapshot（修缺陷 2）

- `ws_dispatch._onQuote`：`quoteStore.update()` 补传 `snapshot: row.snapshot`
- `holdings_push.applyQuote`：同样补传 `snapshot: row.snapshot`

### 回归测试

- `tests/client/components/App.test.js`：模拟「已登录 mount」（auth 预置 token+user）→ 断言 `holdingsStore._startWatchers()` 被调用。修复前红线（未调用），修复后绿。
- `tests/client/stores/daypnl_livepush.test.js`：真实 quote store + 真实 `createDayPnlRecompute` + 真实 `calcDayPnl`，验证 live push 带 snapshot → `prev_close` 写入 → `day_pnl` 非 null（已在上次会话创建）。

### 不做的事

- ❌ 不改 auth watch 为 `immediate: true`（会 double-bootstrap 竞态，`onMounted` 已有 bootstrap 调用）
- ❌ 不改 `useT0DayPnl.getDayPnl` / `calcDayPnl`（公式与 null 语义正确）
- ❌ 不引入轮询（延续 v114.2 无轮询策略）

## 时序

```
刷新 (token 已持久化)
  → auth store 同步恢复 → isAuthenticated=true
  → onMounted: _startWatchers() 启动 quote.tick 重算 watcher + bootstrap() 拉持仓
  → subscribe_ack / REST snapshot / live push(snapshot 转发) 到达 → quoteStore.prev_close 写入
  → quoteStore.tick++ → recomputeAll() → positions[].day_pnl = calcDayPnl(...) 非 null
  → HoldingsPanel 读行字段 → 当日盈亏列显示
```

## 改动文件清单

| 层 | 文件 | 改动 |
|---|---|---|
| 前端 | `client/src/App.vue` | onMounted 补 `_startWatchers()` |
| 前端 | `client/src/stores/ws_dispatch.js` | `_onQuote` 转发 `snapshot` |
| 前端 | `client/src/stores/holdings_push.js` | `applyQuote` 转发 `snapshot` |
| 测试 | `tests/client/components/App.test.js` | 新增：已登录 mount 启动 watcher 回归 |
| 测试 | `tests/client/stores/daypnl_livepush.test.js` | 新增：live push snapshot → day_pnl 非 null |
| 知识库 | `openspec/specs/frontend/spec.md` | REQ-FE-533 补「已登录刷新启动」约定 |

## 关联

- 上游：`openspec/specs/frontend/spec.md` §REQ-FE-533（v114.2 当日盈亏）
- 触发：v119 token 持久化（8cf99db）后，刷新场景首次暴露 watcher 未启动缺陷
