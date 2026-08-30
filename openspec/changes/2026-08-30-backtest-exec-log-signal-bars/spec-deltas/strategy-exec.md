# strategy-exec delta — backtest-exec-log-signal-bars

## MODIFIED: REQ-SE-003 (Backtrader 引擎) — execution_log 仅记信号 bar

**原行为**：`run_backtest` 组装 `backtest_result.execution_log` 时把 `progress_log`（逐 K 线全量）**全量**追加（超限 `_MAX_BAR_ENTRIES=2000` 采样）。长回测前端「执行日志」Tab 被 K 线记录刷屏。

**新行为**：execution_log 的 `phase="bar"` 段**只记触发 buy/sell_signal 的 K 线**：
- 遍历 `collector.signals`，每条按 `stime` 从 `progress_log` 查回 `bar_idx/close/position/equity`，追加一条 `phase="bar"` 记录
- `msg` = `<signal_type> vol=<volume> (<策略 msg>)`（信号 msg 为空则不带括号）
- 信号 `stime` 在 `progress_log` 查不到 → `bar_idx/position/equity=None`，`close` 兜底用信号 `price`
- 逻辑抽纯函数 `_build_signal_bar_entries(signals, progress_log)`

**不变**：
- `best.progress_log` / `best.equity_curve` **全量逐 bar 保留**（权益曲线、进度 Tab 仍消费全量）
- 字段名不变（`bar_idx/stime/close/position/equity/msg`），前端列渲染零破坏
- `signal_log` / audit（`write_audit_batch`）不动

#### Scenario: 长回测执行日志只显信号 bar

- **WHEN** 双均线策略回测 5000 根 K 线，共触发 6 条 BUY/SELL 信号
- **THEN** `backtest_result.execution_log` 中 `phase==="bar"` 的记录 = 6 条（= 信号数，非 5000）
- **AND** `best.equity_curve` 长度 = 5000（全量保留）
- **AND** 每条信号 bar 记录含 `stime`（触发 K 线时间）+ `close`/`position`/`equity`（查回 progress_log）
