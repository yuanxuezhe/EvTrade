# strategy-exec delta — drop-fullbar-progress

## MODIFIED: REQ-SE-003 (Backtrader 引擎) — backtest_result 不再存全量 bar

**原行为**（backtest-exec-log-signal-bars 后）：`best` 仍含 `progress_log`（逐 bar 全量）+ `equity_curve`（逐 bar），供前端进度 Tab + 权益曲线图。

**新行为**：`run_backtest` 不再把 `progress_log` / `equity_curve` 落进 `backtest_result.best`：
- `best` = `{pnl, pnl_pct(小数), win_rate, trades_count, trades, signal_log}`（去掉 progress_log / equity_curve）
- `progress_log` 降级为回测 run 内的**内存缓冲**：仅供 `_build_signal_bar_entries` 取触发信号 bar 的 bar_idx/close/position/equity 写进 `execution_log`，回测结束即丢弃，不持久化
- 顶层 `backtest_result`（`pnl/pnl_pct/final_value/initial_cash/bars_count/sharpe/signal_log/total_bars/execution_log`）不变
- 服务端 `get_task_signals` backtest 分支 `best.get("progress_log", [])` → 新任务返 `[]`（无需改代码）

#### Scenario: 回测结果 blob 不含全量 bar

- **WHEN** 双均线策略回测 5000 根 K 线，触发 6 条信号
- **THEN** `backtest_result.best` **不含** `progress_log` / `equity_curve` 字段
- **AND** `backtest_result.execution_log` 中 `phase==="bar"` = 6 条（= 信号数），每条带 `equity`/`close`/`position`/`stime`
- **AND** `server get_task_signals` 返 `progress=[]`（进度时间轴不再回填全量 bar）
- **AND** 前端权益曲线用 `execution_log` 信号 bar 的 `{stime, equity}` 绘制（不依赖全量 bar）

## ADDED: 前端权益曲线改用执行日志信号 bar

- TaskDetail 权益曲线图 `renderChart`：权益线 = `execution_log` 中 `phase==='bar'` 的 `{stime, equity}`（起点用 `initial_cash` 作成本基准）；BUY/SELL 散点仍来自 `best.trades`
- 去掉「收盘价」series（依赖全量 `progress_log`，已不落地）
- 删「进度」Tab（逐 bar 表格）
- 无信号 bar 时（旧任务 progress 空 / 无信号）曲线不画线（`|| []` 兜底，不报错）
