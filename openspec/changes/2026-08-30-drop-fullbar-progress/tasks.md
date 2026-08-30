# Tasks: drop-fullbar-progress (2026-08-30)

> 每个 task = 1 个 commit（v6 单 commit 单目的）。接 `backtest-exec-log-signal-bars`。

## P0 — change 骨架

- [ ] **commit 0 (骨架)** — proposal/tasks/spec-delta 三文件

## P1 — 后端: best 不再存全量 bar

- [ ] **commit 1 — feat(strategy-exec) backtest.py**
  - `run_backtest`：删 `equity_curve` 派生；`best` 删 `progress_log` + `equity_curve` 两字段
  - `progress_log` 降级 run 内内存缓冲（仅供 `_build_signal_bar_entries`），docstring 更新
  - 服务端 `get_task_signals` 无改动（`best.get("progress_log",[])` 自动空）
  - 验收：`best` keys 不含 progress_log/equity_curve；import OK

## P2 — 前端: 删进度 Tab + 曲线改用 execution_log

- [ ] **commit 2 — feat(client) TaskDetail.vue**
  - 删「进度」Tab（template）+ `progressData`/`progressMinEquity`/`progressMaxEquity` + 赋值
  - `renderChart`：权益线改用 execution_log `phase==='bar'` 的 {stime, equity}（起点 initial_cash）；删收盘价 series；无信号 bar 不画
  - 验收：`npm run build` 不报 import 错；无 leftover progressData/equity_curve 引用

## P3 — 知识库 + spec 同步

- [ ] **commit 3 — docs(knowledge+spec)**
  - `strategy-exec/spec.md` REQ-SE-003：backtest_result best 契约去 progress_log/equity_curve
  - `Backtrader引擎.md`：best 结构 + 权益曲线/进度 Tab 说明
  - `脚本策略模块.md`：/signals progress 语义（新任务空）
  - `策略开发与运行.md`：进度 Tab 删除
  - 验收：grep progress_log/equity_curve 在知识库只剩「已删除」说明

## P4 — 归档

- [ ] **commit 4 — docs(openspec) 归档** — mv 到 archive + AGENTS 行

## 验证 (v6 完成自查)

- [ ] `pytest tests/strategy_exec/ server/tests/ -q` 全过
- [ ] `npm run build` OK
- [ ] E2E：best 无全量 bar；execution_log 信号 bar 带 equity
- [ ] 前端无进度 Tab；曲线用信号 bar
- [ ] 知识库 + spec 同步；不自动 push
