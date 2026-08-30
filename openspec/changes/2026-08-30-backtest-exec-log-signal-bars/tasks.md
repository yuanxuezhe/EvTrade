# Tasks: backtest-exec-log-signal-bars (2026-08-30)

> 每个 task = 1 个 commit（v6 单 commit 单目的）。

## P0 — change 骨架

- [ ] **commit 0 (骨架)**
  - 新建 `openspec/changes/2026-08-30-backtest-exec-log-signal-bars/{proposal.md, tasks.md, spec-deltas/strategy-exec.md}`
  - 验收：`ls` 三文件存在

## P1 — 后端执行日志改「仅信号 bar」

- [ ] **commit 1 — feat(strategy-exec) backtest.py**
  - `run_backtest` 内 exec_log bar 段：删原 `_MAX_BAR_ENTRIES=2000` 逐 bar 全量/采样逻辑
  - 新增纯函数 `_build_signal_bar_entries(signals, progress_log)`（`_get_analyzer_value` 旁）：遍历 signals，按 stime 查 progress_log 取 bar_idx/close/position/equity，msg=`signal_type vol=<v> (<策略 msg>)`
  - `progress_log` / `best.equity_curve` 全量保留不动
  - 验收：`uv run python -c "from strategy_exec.engines.backtrader.backtest import _build_signal_bar_entries"` 不报错

## P2 — 单测

- [ ] **commit 2 — test(strategy-exec) test_signal_bar_entries.py**
  - 6 case：空 signals→[] / BUY 命中 progress / 多信号按 stime 对齐 / miss 兜底 price / 仅信号非全量(5bar 1信号→1条) / 同 stime 取首
  - 验收：`pytest tests/strategy_exec/test_signal_bar_entries.py -q` 6 passed；全套守 111

## P3 — 前端 tag 文案 + 知识库 + spec 同步

- [ ] **commit 3 — docs(knowledge+frontend)**
  - `client/src/components/strategy/TaskDetail.vue`：执行日志摘要 tag `bars: N` → `信号 bar: N`（语义对齐）
  - `openspec/specs/strategy-exec/spec.md` REQ-SE-003：补 execution_log「仅信号 bar」语义
  - `知识库/策略服务/Backtrader引擎.md` 执行日志段：逐 bar 全量 → 仅信号 bar
  - 验收：`grep 信号 bar 知识库/策略服务/Backtrader引擎.md` 命中；前端 build 不报 import 错

## P4 — 归档

- [ ] **commit 4 — docs(openspec) 归档**
  - `mv changes/2026-08-30-backtest-exec-log-signal-bars → archive/`
  - `openspec/AGENTS.md` 加归档行
  - 验收：`openspec/changes/` 只剩 archive

## 验证 (v6 完成自查)

- [ ] `pytest tests/strategy_exec/ -q` 守 111（含新增 6）
- [ ] `execution_log` 中 `phase==="bar"` 条数 = 信号数
- [ ] `best.equity_curve` 全量（长度 = K 线数）
- [ ] 知识库 + spec 同步；每 commit 单目的；不自动 push
