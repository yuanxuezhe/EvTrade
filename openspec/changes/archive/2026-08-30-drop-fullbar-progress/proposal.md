# 回测详情去掉全量 bar (进度 Tab + 权益曲线数据源) (2026-08-30)

> 用户拍板 2026-08-30（接 `backtest-exec-log-signal-bars` 后）：回测任务详情里**「进度」Tab 列出所有 bar**（逐 K 线的 bar_idx/时间/收盘/持仓/现金/权益），去掉它；**也不需要记录所有 bar**；权益曲线图**不用全量 bar 画**——「只根据权益和日志里面的时间戳即可」（即用 execution_log 信号 bar 的 equity + stime 画）。执行日志只记触发信号的 bar（上一步已做）。

## Why

- 上一 change 只把**执行日志**改成「仅信号 bar」，但 `best.progress_log`（全量逐 bar）与 `best.equity_curve`（全量）仍在落库，且被两个 UI 消费：
  - **进度 Tab**（TaskDetail）：服务端 `/signals` 把 `best.progress_log` 当 `progress` 返回 → 前端逐行表格（= 用户说的"列出所有 bar"）
  - **权益曲线图**（TaskDetail ECharts）：`equity_curve` 画权益线 + `progress_log` 画收盘价虚线
- 全量逐 bar 数据对回测详情价值低（长回测数万条），blob 膨胀、前端表格刷屏。信号触发的快照已足够表达"哪里交易了、当时权益多少"。

## What

- **后端**：`run_backtest` 不再把 `progress_log` / `equity_curve` 落进 `backtest_result.best`（删两个字段 + 删 `equity_curve` 派生）。`progress_log` 降级为 run 内**内存缓冲**，仅供 `_build_signal_bar_entries` 取触发信号 bar 的 equity/close/position 写进 execution_log，结束即丢弃。
- **服务端**：`get_task_signals` backtest 分支 `best.get("progress_log", [])` → 新数据自动返 `[]`（**无需改代码**，blob 里没了就是空）。
- **前端**：
  - 删「进度」Tab（template + `progressData`/`progressMinEquity`/`progressMaxEquity` script 状态 + 赋值）。
  - 权益曲线图 `renderChart`：权益线改用 `execution_log` 中 `phase==='bar'` 的 `{stime, equity}`（起点用 `initial_cash` 兜底成本基准）；**去掉收盘价 series**（依赖全量 `progress_log`）；无信号 bar 时不画线（旧任务兼容）。
- **保留**：`signal_log` / `trades` / `win_rate` / `pnl` / `execution_log` 不动；进度环（BatchTasksTable，REQ-FE-546）不动（那是运行中 task.progress，非逐 bar）。

## 不做什么

- 不动 `patched_next` 逐 bar 采集（内存里仍要采，供信号 bar 快照）——只是**不再落库**。
- 不动 `task.progress` 实时节流推送（运行进度环数据源）。
- 不动 iquant / broker。
- 不做 DB 迁移（blob 字段删除是数据层自然淘汰，存量行的旧 blob 仍可读，前端 `|| []` 兜底）。

## 影响面

| 模块 | 影响 |
|---|---|
| `strategy_exec/engines/backtrader/backtest.py` | `run_backtest` 删 equity_curve 派生 + best 删 progress_log/equity_curve；docstring 更新 |
| `server/services/script_strategy/tasks.py` | 无代码改动（`best.get("progress_log", [])` 自动空） |
| `client/src/components/strategy/TaskDetail.vue` | 删进度 Tab + renderChart 改用 execution_log + 清 script 状态 |
| `openspec/specs/strategy-exec/spec.md` | REQ-SE-003 backtest_result 契约：best 去 progress_log/equity_curve |
| `知识库/策略服务/Backtrader引擎.md` | best 结构 + 权益曲线/进度 Tab 说明 |
| `知识库/前端/页面/策略开发与运行.md` + `知识库/后端服务/策略引擎/脚本策略模块.md` | 进度 Tab 删除 + /signals progress 语义 |

## 数据安全 checklist

- [x] 只删 best 内两字段，不动 DB schema / 不删表
- [x] 存量行旧 blob 仍含 progress_log/equity_curve，前端 `|| []` 兜底，不报错
- [x] 单测纯函数不打 DB

## 验收 checklist

- [ ] `pytest tests/strategy_exec/ server/tests/ -q` 全过（无回归）
- [ ] `npm run build` 不报 import 错
- [ ] E2E 真实 run_backtest：`best` 无 progress_log/equity_curve；execution_log 信号 bar 带 equity（可画曲线）
- [ ] 前端：详情无「进度」Tab；权益曲线用信号 bar 的权益+时间画；收盘价 series 消失
- [ ] 旧任务（blob 有全量）不报错（progress 空 / 曲线无信号时不画）
- [ ] 知识库 + spec 同步；每 commit 单目的；不自动 push
