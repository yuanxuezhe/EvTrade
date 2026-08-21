# 2026-08-10-holdings-auto-sub-batch — 持仓过多时 auto-sub 全量订阅 + WS 新持仓批量合并

## Why

持仓数很大（如 2197 只）时，broker 重连 / 初始化会通过 WS `pos_push` 洪峰逐条推送新持仓，前端产生大量刷屏日志：

1. **auto-sub 逐只订阅**：`holdings_bootstrap._syncQuoteSubs` 的 watch 每收到一条 push 触发一次，每次只带 1 个新 code，调 `quote.subscribe([code])` 逐只订阅 + 逐条日志「持仓订阅增量: +1」。
   - `quote.js subscribe()` 内部**已有** `>100 → [''] 全市场` 逻辑，但 `_syncQuoteSubs` 每次只传 1 个 code，永远走不到该分支。
2. **WS 新持仓逐条处理**：`holdings_push.applyPositionUpdate` 对新持仓逐条 `positions.value.unshift()` + 逐条日志「新持仓: X」。2197 条推送 → 2197 条日志。

用户原话 (2026-08-10)：
- 「当idb里面加载的持仓数据超过100，则用空字符串表示全量订阅，只订阅一次就OK了」
- 「ws新持仓能否批量一次处理OK？」

## What Changes

### 前端 auto-sub（`client/src/stores/holdings_bootstrap.js`）

`_syncQuoteSubs` 加全市场阈值：

- 持仓 codeSet **去重后 > 100** → 调 `quote.subscribe(全量 codes)` 一次（`quote.js` 内部 `>100` 转 `['']` 全市场），并置 `_fullMarketSubscribed=true`
- 已全市场订阅时**直接 return**：不再逐只增量订阅，也不再逐条刷日志
- 持仓缩回 **≤100** → 退出全市场模式（清标志 + 清 `_lastSubscribedCodes`），恢复逐只增量订阅

阈值常量 `FULL_MARKET_THRESHOLD = 100`，与 `quote.js subscribe()` 既有 `>100 转 ''` 约定对齐。

### 前端 WS 新持仓批量（`client/src/stores/holdings_push.js`）

`applyPositionUpdate` 新持仓路径改**短窗口批量合并**：

- 新持仓（positions 中无该 code）先入 `_pendingNewPositions`（按 stock_code 去重，同 code 保留最新）
- 短窗口 `NEW_POS_BATCH_MS = 100`（trailing debounce）静默后，一次 `positions.value.unshift(...batch)` + 一条「批量新增 N 只新持仓」日志
- 洪峰被合并成少数几次 flush（甚至一次），从 N 条日志降到 O(几) 条
- 已有持仓的「持仓刷新」路径**不变**（即时整条 ref 替换，实时性不受影响）

### 不在范围内

- ❌ 不动后端 `handle_pos_push` / `pos-push-diff-skip`（REQ-PUSH-034 已做无变化跳过；洪峰由前端侧吸收）
- ❌ 不动 `quote.js subscribe()` 既有 `>100 → ''` 逻辑（保持，前端 auto-sub 只负责触发全量路径）
- ❌ 不弹窗 / 不改 UI，仅日志与订阅行为

## 改动文件清单

| 层 | 文件 | 改动 |
|---|---|---|
| 前端 | `client/src/stores/holdings_bootstrap.js` | `_syncQuoteSubs` 加全市场阈值 + `_fullMarketSubscribed` 标志 |
| 前端 | `client/src/stores/holdings_push.js` | `applyPositionUpdate` 新持仓批量合并 |
| 知识库 | `openspec/specs/quotes/spec.md` | 新增 REQ-QUOTE-007：前端 auto-sub 全市场阈值 |
| 知识库 | `openspec/specs/frontend/spec.md` | 新增 REQ-FE-531：WS pos_push 新持仓批量合并 |

## 落地约束

- ✅ 与 OpenSpec 工作流一致：先补 spec → 再写代码
- ✅ 阈值 100 与 `quote.js` 既有约定对齐，不引入第二个魔法数
- ✅ 不自动 push（用户硬性偏好）
- ✅ 浏览器/ws 实测：连 broker → 全量持仓只订阅一次（auto-sub 一条「切全市场订阅」）+ 新持仓合并成一条「批量新增 N 只」

## 关联

- 上游：`quotes/spec.md` REQ-QUOTE-006（pattern 订阅，`''` = 全市场，2026-07-10）
- 上游：`push/spec.md` REQ-PUSH-034（pos_push 无变化跳过落库与广播，2026-07-31）
- 前端：`quote.js` subscribe() `>100 → ['']` 既有分支（v15 quote-snapshot-subscribe）
