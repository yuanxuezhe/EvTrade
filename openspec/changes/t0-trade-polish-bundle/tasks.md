# Tasks — t0-trade-polish-bundle

按 scope 拆 5 commit, 单 change。 顺序按依赖 (lib 抽 → 校验 → 缓存 → 重复清理 → 排序快捷键 → 验证归档)。

## 1. lib/t0-calc.js 抽纯函数层 (commit: refactor(client))

**目标**: 把 useT0Balance 里的纯函数 (roundToLot / orderPrice 决策 / insufficientCash/Position) 抽到零依赖 lib, 单测覆盖, useT0Balance 改成"消费 lib 的 reactive wrapper"

- [x] 1.1 新建 `client/src/lib/t0-calc.js`, 导出 5 函数:
  - `roundToLot(vol, lotSize=100)` — 整手 floor
  - `calcBalanceQty({vol, todayBuy, todaySell})` — 配平量 + side + error
  - `calcInsufficientCash({side, qty, price, cash})` — 返 `{ok, need, have, gap}`
  - `calcInsufficientPosition({side, qty, currentVolume})` — 同结构
  - `resolvePriceTypeCode(priceType)` — 字符串 → broker priceTypeCode
- [x] 1.2 新建 `client/tests/lib/t0-calc.test.js`, 覆盖 5 函数 + 边界 (qty=0 / cash=0 / NaN / 负数) ≈ 30 用例
- [x] 1.3 重构 `client/src/composables/useT0Balance.js`: computed 派生改为从 `@/lib/t0-calc` import; 暴露同名 API 但内部实现引用 lib (roundToLot 应用 balanceCoeff 后委托 lib; insufficientCash/Position 委托 lib 返 boolean)
- [x] 1.4 跑 `npm test -- --run` → 133/133 全过 (103 旧 + 30 新); `npx vite build` OK; grep `import.*from.*t0-calc` 在 useT0Balance.js = 1

## 2. 资金/持仓校验接入 (commit: feat(client): t0Trade 资金/持仓校验)

**目标**: 主表买/卖/配平按钮 disabled 条件加 insufficientCash/Position, tooltip 注明缺额

- [x] 2.1 T0Trade.vue 操作列 button disabled 条件:
  - `买X%`: `isBuyDisabled(row) || submitting || !cashCheck.ok` (cash 不足) → `buyState(row).disabled`
  - `卖X%`: `submitting || !positionCheck.ok` (持仓不足) → `sellState(row).disabled`
  - `配±N`: 现有条件 + cash/position check (按 side) → `balanceState(row).disabled`
- [x] 2.2 加 `<el-tooltip>` 显示"资金 ¥X 不足 / 缺持仓 Y 股"
- [x] 2.3 校验走 `lib/t0-calc.js` 纯函数, 不再 import 计算常量 (单一权威): 新建 `useT0TradeButtons.js` composable 委派 lib
- [x] 2.4 单测: `tests/composables/useT0TradeButtons.test.js` (新, 18 用例) — mock cash=0 / position=0 / volume 不足, 验证按钮 disabled

## 3. t0Stats 30s 缓存 + 差量更新 (commit: perf(client): t0Stats 缓存)

**目标**: 30 持仓只首次全量拉, 后续命中缓存; ws push 即时 invalid

- [x] 3.1 新建 `client/src/composables/useT0Stats.js`:
  - 内部 Map `_cache: stockCode -> {data, ts}`, TTL 30s (module-level singleton)
  - `getStats(code, force=false)`: 命中返 / miss fetch 后 set
  - `loadAll(codes[])`: 并发 fetch, 复用 getStats 单标的
  - `invalidate(code)` / `invalidateAll()`
  - `_resetCache()` / `_size()` (测试用)
- [x] 3.2 T0Trade.vue 改 `loadAllT0Stats` → `useT0Stats.loadAll(codes)`; `watch holdings.length` 改 diffOnly: 新增 fetch, 删除标的无需动作
- [x] 3.3 `client/src/stores/holdings_push.js` ws handler: `applyOrderPush` / `applyTradePush` 末尾 `useT0Stats.invalidate(stock_code)`
- [x] 3.4 跨日切换 `holdings_bootstrap._resolveActiveDay` 检测 trd_date 变化 → `useT0Stats.invalidateAll()`
- [x] 3.5 单测 `tests/composables/useT0Stats.test.js` — 14 用例: TTL 过期 / invalidate / 并发 / 错码 / force / 空 codes / 去重

## 4. 副行 sparkline 移除 (commit: refactor(client): t0Trade 副行减负)

**目标**: 删重复 SVG, 副行 30 日数据改 hover-only popover; 移动端不渲染

- [x] 4.1 T0Trade.vue 副行 `<el-table-column type="expand">` 内部: 移除 `<svg.mini-sparkline>` 150x30 SVG; 移除 `sparklinePoints` / `sparklinePath` / `sparklineLast` / `loadSparkline` 4 函数 → 改 `ensureHistory30d`
- [x] 4.2 副行"30天"字段改为 `<el-popover trigger="hover">`, reference 显示 "¥{last} ↑/↓", content 列 D-1..D-30 数值 (lazy load via @show)
- [x] 4.3 CSS `@media (max-width: 768px) .sub-popover { display: none }` 桌面 hover, 移动端静态隐藏 (避免 mobile hover 不工作)
- [x] 4.4 验证: `npm test` 165/165 全过, build OK, grep `sparkline` in T0Trade.vue = 0

## 5. 排序 + 快捷键 (commit: feat(client): t0Trade 排序+快捷键)

**目标**: sortable 列 + 全局快捷键 B/S/P/↑↓/Enter, uiStore 加 toggle

- [ ] 5.1 T0Trade.vue 主表 `<el-table>` 加 `sortable="custom"` + `@sort-change` handler, 默认按"浮盈% desc" (与今入仓习惯一致)
- [ ] 5.2 state: `sortBy = ref('return_rate')`, `sortOrder = ref('descending')`, `selectedRowCode = ref(null)`; computed `sortedRows` 用 lodash.orderBy 或手写
- [ ] 5.3 新建 `client/src/composables/useT0Keybindings.js`:
  - `addEventListener('keydown', handler)` (在 onMounted 加 / onUnmounted 移)
  - 字母键 B/S/P → 调对应 row 的 quickBuy/Sell/Balance (需 selectedRowCode)
  - ↑↓ → 改 selectedRowCode (按 sortedRows 顺序); Enter → 开抽屉
  - 守门: `if (['input','textarea','select'].includes(target.tagName)) return`; `if (drawerVisible.value) return`
- [ ] 5.4 `client/src/stores/ui.js` 加 `t0Keybindings: true` (默认开), `toggleT0Keybindings()` action
- [ ] 5.5 单测 `tests/client/composables/useT0Keybindings.test.js` — 输入框不触发 / 抽屉打开不触发 / 5 键 mapping 5 action

## 6. 同步 OpenSpec specs + 验证 + 归档 (commit: docs(openspec): sync t0-trade-polish scenarios)

- [ ] 6.1 同步 `openspec/specs/frontend/spec.md`:
  - MODIFIED `QuotePanel...` 等已有 REQ 不动, 新增 REQ: `T0Trade 主表快速操作 (b/A/C/E/F bundle)`
  - 新增 6 个 Scenario: 资金不足按钮 disabled / 持仓不足按钮 disabled / t0Stats 缓存命中 / 排序点击 / 快捷键触发 / 副行 popover hover
- [ ] 6.2 同步 `openspec/specs/trading/spec.md`:
  - MODIFIED 既有"下单校验"REQ, 加 insufficientCash/Position 校验为 spec 要求
- [ ] 6.3 全量验证:
  - `cd client && npm test -- --run` → 133+ ≥ 全部通过
  - `cd client && npx vite build` → OK
  - `grep -r 'lib/t0-calc' client/src/composables` → ≥ 1
  - `grep -r 'sparkline' client/src/views/T0Trade.vue` → 0
- [ ] 6.4 dev 启后浏览器走 `/t0-trade`:
  - 30 持仓账户, 主表首屏响应 (缓存 miss 一次, 不卡); 滚动/点击 watch holdings.length 应仅新标的 fetch
  - 资金不足时买按钮 disabled + hover tooltip 显示缺额
  - 排序点击表头响应 (浮盈% desc → 切 asc)
  - 按 B/S/P 触发对应行操作; ↑↓ 切换行; Enter 开抽屉
  - 副行 hover 显示 30 日明细
- [ ] 6.5 归档: `openspec archive t0-trade-polish-bundle --change 2026-07-05-t0-trade-polish-bundle` → `openspec/changes/archive/2026-07-05-t0-trade-polish-bundle/`
