# Tasks: his-hq-aggregate-bars (2026-08-30)

> 每个 task = 1 个 commit（v6 单 commit 单目的）。
> 整体按 P0→P1→P2→P3 顺序推进。

## P0 — change 骨架

- [ ] **commit 0 (骨架)** — 已通过 proposal/tasks/spec-delta 文件创建完成

## P1 — strategy_exec 端实现

- [ ] **commit 1 — hq_history 删 mock + 强制 1m + 调 aggregator**
  - 删 `hq_history.py` 的 `_is_his_hq_mock_mode()` 函数
  - 删 `if _is_his_hq_mock_mode(): ...` 短路分支
  - 删 `_read_sys_config` import
  - 改 `fetch_bars()` 内部：
    - 收到 `(stock_code, start_date, end_date, period, fields)` → 内部用 `period='1m', fields=['close']` 调 broker
    - 收到 1m bars → 调 `aggregator.aggregate_bars(bars, user_period, start_date, end_date)` 聚合
    - 返聚合后的 bars
  - 验收: `uv run python -c "from strategy_exec.market_data.hq_history import fetch_bis; ..."` 测可调用 (本地 broker 不在线会 raise HQHistoryError, 但 import 不报错)

- [ ] **commit 2 — 删 init_db seed his_hq_test_mode + 启动日志 + 删 sys_config 模块**
  - 删 `server/infra/db.py` `_run_seed_cantrdstktypes_via_session` 里 his_hq_test_mode 段
  - 删 `server/main.py` 启动日志 his_hq_test_mode 段
  - 删 `strategy_exec/strategy_exec/data_access/sys_config.py` 整文件
  - 验收: `git grep his_hq_test_mode` 在 server/main.py / server/infra/db.py / strategy_exec 都无命中

- [ ] **commit 3 — 删 mock_history + cleanup endpoint + 旧单测**
  - 删 `strategy_exec/strategy_exec/market_data/mock_history.py`
  - 删 `tests/strategy_exec/test_mock_history.py`
  - 删 `tests/strategy_exec/test_sys_config_cache.py`
  - 删 `server/tests/strategy/test_stale_queued_cleanup.py`
  - 删 `server/services/script_strategy/batches.py` 的 `mark_stale_queued_failed` + `STALE_CLEANUP_ERROR_MSG`
  - 删 `server/api/script_strategy/strategies.py` 的 `stale_queued_cleanup_endpoint`
  - 删 `server/services/script_strategy/__init__.py` 的相关 export
  - 验收: `git grep mark_stale_queued_failed` / `git grep STALE_CLEANUP_ERROR_MSG` 0 命中
  - 保留: `list_stale_queued_tasks` + GET `/stale-queued` 端点 (admin 监控用)

- [ ] **commit 4 — 端到端验收**
  - 重启 strategy_exec
  - admin POST 回测 (sid=12 single, 1d period)
  - 验证:
    - strategy_exec 日志显示 broker period=1m 请求 + 收到 N 根 1m close
    - aggregator 合成 1d K 线
    - run_backtest 跑完 status=finished + pnl 有值
  - 留 trace 在 commit message

## P2 — 单测

- [ ] **commit 5 — aggregator 单测**
  - 新 `strategy_exec/strategy_exec/market_data/aggregator.py`:
    - `aggregate_bars(bars_1m, user_period, start_date, end_date) -> List[Dict]`
    - 1m 透传
    - 5m / 15m / 30m / 60m 聚合 (OHLCV: open=第一根, close=最后一根, high=max, low=min, volume=sum)
    - 1d 聚合: 同日 09:31~15:00 全聚合
    - 跳过周末 (Sat/Sun)
    - 跳过非交易时段 (11:30~13:00 午休)
  - 新 `tests/strategy_exec/test_aggregator.py`:
    - 1m 透传 (10 cases)
    - 5m OHLCV 聚合 (4 cases)
    - 15m / 30m / 60m 聚合 (3 cases)
    - 1d A股聚合 + 周末跳过 (4 cases)
    - 边界: 跨日 / 午休 / 不足 N 根 (3 cases)
  - 验收: 10+ 单测全过
  - 跑全基线: `pytest server/tests/ tests/strategy_exec/ -q` 守住 (142 - 25 mock/cleanup + 14 aggregator ≈ 131 passed)

## P3 — 文档 + 归档

- [ ] **commit 6 — spec-delta merge + 归档**
  - 改 `openspec/specs/strategy-exec/spec.md`:
    - 删 REQ-SE-013 整段 (his_hq_test_mode mock)
    - 删 REQ-SE-014 整段 (cleanup)
    - 改 REQ-SE-012 段: broker 永远 1m + strategy_exec 聚合 + A股交易日历
  - 归档: `mv openspec/changes/2026-08-30-his-hq-aggregate-bars openspec/changes/archive/`

- [ ] **commit 7 — 知识库同步**
  - 改 `知识库/策略服务/历史行情.md`: 大幅改写, 删 mock 段, 加"1m 拉 + 聚合"流程图
  - 改 `知识库/策略服务/架构概览.md`: 删 mock_history 引用
  - 改 `strategy_exec/README.md`: 删"离线开发模式"段
  - 删 `server/infra/db.py` 注释里的 his_hq_test_mode 引用

## 验证（v6 完成自查）

- [ ] pytest strategy_exec/strategy_exec/tests/test_aggregator.py → 0 fail
- [ ] pytest server/tests/ + tests/strategy_exec/ → 基线守住 (~131 passed)
- [ ] 端到端实测 (commit 4 留 trace): admin 提交回测 → status=finished + pnl 有值
- [ ] cd client && npm run build → 无报错 (前端无改动)
- [ ] git diff --stat 每 commit 单目的
- [ ] 不动 MySQL schema / 行 (仅删 API/模块/单测)
- [ ] sys_config 表里 his_hq_test_mode 行不强删 (兼容历史)