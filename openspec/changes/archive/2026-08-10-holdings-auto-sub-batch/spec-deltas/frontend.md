# spec-delta: frontend — WS pos_push 新持仓批量合并

## REQ-FE-531（新增）：WS pos_push 新持仓批量合并（holdings-auto-sub-batch 2026-08-10）

`holdings_push.applyPositionUpdate` 处理「新持仓」（positions 中无该 code）MUST 批量合并：

- 新持仓先入 `_pendingNewPositions`（**按 stock_code 去重**，同 code 多次推送只保留最新）
- 短窗口 `NEW_POS_BATCH_MS = 100`（trailing debounce）静默后，一次 `positions.value.unshift(...batch)` + 一条「批量新增 N 只新持仓」日志
- 洪峰（如 broker 重连全量推 2197 只）被合并成少数几次 flush，从 N 条日志降到 O(几) 条
- 已有持仓的「持仓刷新」路径**不变**（即时整条 ref 替换，实时性不受影响）

#### Scenario: 重连全量推不刷屏

- **GIVEN** broker 重连后 WS pos_push 洪峰 2197 条
- **WHEN** 前端逐条收到 `pos_push`
- **THEN** 新持仓 MUST 在 100ms 静默窗口合并，最后一次 flush
- **AND** 日志 MUST 只出现一条「批量新增 2197 只新持仓」（或少量分组），非 2197 条

#### Scenario: 实时单只新持仓即时合并

- **WHEN** 用户买入一只新标的，broker 推 1 条 pos_push
- **THEN** 100ms 后该持仓 MUST 进入 positions
- **AND** 日志「批量新增 1 只新持仓」

## Cross References

- `quotes/spec.md` REQ-QUOTE-007（前端 auto-sub 全市场阈值）
- `push/spec.md` REQ-PUSH-034（pos_push 无变化跳过落库与广播）
