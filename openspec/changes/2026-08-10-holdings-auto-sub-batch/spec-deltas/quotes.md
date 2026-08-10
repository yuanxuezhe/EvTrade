# spec-delta: quotes — 前端 auto-sub 全市场阈值

## REQ-QUOTE-007（新增）：前端 auto-sub 全市场订阅阈值（holdings-auto-sub-batch 2026-08-10）

持仓自动订阅（`holdings_bootstrap._syncQuoteSubs`）MUST 在持仓代码数 > 100 时切 `''` 全市场订阅一次：

- 触发条件：holdings 的 positions 代码**去重后数量 > 100**
- 行为：调 `quote.subscribe(全量 codes)` 一次（`quote.js` 内部 `>100` 转 `['']` 全市场），并置 `_fullMarketSubscribed=true`
- 已全市场订阅后，后续 WS `pos_push` 不再逐只增量订阅，也不逐条刷日志
- 持仓缩回 **≤100** → 退出全市场模式，恢复逐只增量订阅
- 阈值 `100` 与 `quote.js subscribe()` 既有 `>100 转 ''` 约定一致

#### Scenario: 持仓洪峰只订阅一次

- **GIVEN** 前端持仓 2197 只（>100）
- **WHEN** broker 重连后 WS pos_push 洪峰逐条到达
- **THEN** `_syncQuoteSubs` 首次见 codeSet>100 时 MUST 调一次 `quote.subscribe(全量 codes)`（后端收 `''` 全市场 pattern）
- **AND** 后续每条 push MUST NOT 再发订阅 / 不刷「持仓订阅增量」日志

#### Scenario: 持仓缩回阈值以下恢复增量

- **WHEN** 持仓从 2197 只降到 ≤100
- **THEN** MUST 退出全市场模式
- **AND** 后续新持仓按逐只增量订阅

## Cross References

- `quotes/spec.md` REQ-QUOTE-006（pattern 订阅，`''` = 全市场）
- `frontend/spec.md` REQ-FE-531（WS pos_push 新持仓批量合并）
