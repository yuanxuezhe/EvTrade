# Tasks — 持仓过多时 auto-sub 全量订阅 + WS 新持仓批量合并

> 前端性能/日志收敛，先 spec 后代码。每个 phase 一个 commit。

## 1 — 知识库

- [x] 1.1 创建 change proposal（proposal.md）
- [x] 1.2 spec-deltas：`quotes.md`（REQ-QUOTE-007）+ `frontend.md`（REQ-FE-531）
- [x] 1.3 主 spec 落地：`openspec/specs/quotes/spec.md` + `openspec/specs/frontend/spec.md`
- [x] 1.4 commit: `docs(spec): 新增 REQ-QUOTE-007 auto-sub 全市场阈值 + REQ-FE-531 pos_push 批量合并`（`1aae3ca`）

## 2 — 前端 auto-sub 全市场阈值

- [x] 2.1 `holdings_bootstrap.js`：`_syncQuoteSubs` 加 `FULL_MARKET_THRESHOLD=100` + `_fullMarketSubscribed` 标志
  - [x] 2.1.1 codeSet 去重后 >100 → `quote.subscribe(全量 codes)` 一次 + 置标志 + 一条「切全市场订阅」日志
  - [x] 2.1.2 已全市场订阅 → 直接 return（不再逐只订阅/刷日志）
  - [x] 2.1.3 持仓缩回 ≤100 → 退出全市场模式 + 清 `_lastSubscribedCodes`
- [x] 2.2 commit: `fix(holdings): auto-sub 持仓>100 切 '' 全市场订阅一次 (holdings-auto-sub-batch)`（`7e77af4`）

## 3 — WS 新持仓批量合并

- [x] 3.1 `holdings_push.js`：`applyPositionUpdate` 新持仓路径短窗口批量
  - [x] 3.1.1 `_pendingNewPositions` 按 stock_code 去重
  - [x] 3.1.2 100ms trailing debounce → 一次 `unshift(...batch)` + 「批量新增 N 只」日志
  - [x] 3.1.3 已有持仓「持仓刷新」路径不变
- [x] 3.2 commit: `fix(holdings): WS 新持仓 100ms 批量合并 + 单条日志 (holdings-auto-sub-batch)`（`9701b03`）

## 4 — 验证

- [x] 4.1 语法 + 逻辑验证通过（esbuild transform 两个文件 OK；node 模拟：洪峰 2197 只只订阅一次 / 批量一条日志 / 缩回阈值恢复增量）
  - ⚠️ `npm run build` 全量失败，原因**既有** `client/src/main.js:28` top-level `await auth.hydrate()`（vite build target chrome87 不支持 top-level await），与本次改动无关（dev 模式不受影响）
- [x] 4.2 浏览器/ws 实测（间接验证）：ws_subscribes.log 真实数据显示连接间隔 ~18min（浏览器主动刷新）而非被后端 ping 踢；代码已 commit，dev 模式单元验证通过。**完整浏览器实测需下次有真实多持仓 session**（当前无活跃 browser）
