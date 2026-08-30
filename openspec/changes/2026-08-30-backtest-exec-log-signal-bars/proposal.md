# Backtest Exec-Log 只记信号 bar (2026-08-30)

> 用户拍板 2026-08-30：回测执行日志（`backtest_result.execution_log`）不要逐 bar 全量记录，**只记触发 buy/sell_signal 的那几根 K 线**——不然 K 线多时消息太多（原逻辑把 `progress_log` 全量灌入，超限采样到 2000 条）。

## Why

- `run_backtest` 组装 `execution_log` 时把 `progress_log`（每根 K 线一条 `{bar_idx,stime,close,position,cash,equity}`）**全量**追加进执行日志，长回测（数千~数万根）时前端「执行日志」Tab 被 K 线记录刷屏。
- 现有 `_MAX_BAR_ENTRIES=2000` 超限采样只是**减量**（仍展示大量非信号 bar），不是用户真正想看的。
- 执行日志的价值 = 阶段时间轴（start/load_script/.../done）+ **哪里触发了信号**。逐 bar 的 close/equity 全量已由 `best.progress_log` / `best.equity_curve` 承担（权益曲线、进度 Tab 消费），执行日志无需重复。

## What

- **执行日志的 bar 段改为「仅信号 bar」**：遍历 `collector.signals`（buy/sell_signal 命中），每条按 `stime` 从 `progress_log` 查回 `bar_idx/close/position/equity`，追加一条 `phase="bar"` 记录（msg = `signal_type vol=<v> (<策略 msg>)`）。
- 抽纯函数 `_build_signal_bar_entries(signals, progress_log) -> List[dict]`（同 `_get_analyzer_value` 旁，便于单测）。
- **`progress_log` / `best.equity_curve` 全量保留不动**——权益曲线、进度 Tab 仍消费全量逐 bar 数据。
- 字段名不变（`bar_idx/stime/close/position/equity/msg`），前端 `TaskDetail.vue` 列渲染零破坏；仅执行日志条数从「≈K 线数」降到「= 信号数」。

## 不做什么

- 不改 `best.progress_log` / `best.equity_curve`（权益曲线全量保留）。
- 不改 `signal_log` / audit（`write_audit_batch` 已单独落地）。
- 不动前端列渲染逻辑；**仅**把执行日志摘要 tag `bars: N` 的语义/文案对齐（现按 `phase==='bar'` 计数，改后 = 信号 bar 数，文案改「信号 bar」）。
- 不动 iquant / broker。

## 影响面

| 模块 | 影响 |
|---|---|
| `strategy_exec/engines/backtrader/backtest.py` | `run_backtest` 内 exec_log bar 段改调 `_build_signal_bar_entries`；新增纯函数 |
| `tests/strategy_exec/test_signal_bar_entries.py` | 新增 6 case（空/BUY 命中/多信号对齐/miss 兜底/仅信号非全量/同 stime 取首） |
| `client/src/components/strategy/TaskDetail.vue` | 执行日志摘要 tag 文案 `bars:` → `信号 bar:`（语义对齐，可选） |
| `openspec/specs/strategy-exec/spec.md` | REQ-SE-003 补 execution_log「仅信号 bar」语义 |
| `知识库/策略服务/Backtrader引擎.md` | 执行日志段：逐 bar → 仅信号 bar |

## 数据安全 checklist

- [x] 纯内存数据变换，不落库、不改 DB schema
- [x] 不删任何数据；`progress_log`/`equity_curve` 全量保留
- [x] 测试不打真实 DB（纯函数）

## 验收 checklist

- [ ] `pytest tests/strategy_exec/test_signal_bar_entries.py` 6 case 全过
- [ ] `pytest tests/strategy_exec/ -q` 守住 111（含新增）
- [ ] `backtest_result.execution_log` 中 `phase==="bar"` 条数 = 信号数（非 K 线数）
- [ ] `best.equity_curve` 仍全量（长度 = K 线数）
- [ ] 前端执行日志 Tab 正常渲染信号 bar（bar_idx/close/position/equity 列有值）
- [ ] 知识库 + spec 同步；每 commit 单目的；不自动 push
