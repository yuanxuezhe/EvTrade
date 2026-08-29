# His-HQ 1m Aggregate — broker his_hq 永远 1m + 策略_exec 端聚合 (2026-08-30)

> 用户拍板 2026-08-30：删 `his_hq_test_mode` 参数；行情**永远**从 broker 拿**1m close**，其他周期在 strategy_exec 端**按 1m + 时间戳自己聚合**。

## Why

**实测（2026-08-30）**：

1. broker his_hq 实际**只返 1m close**（用户描述）：
   - `period=1m` 600519.SH 20250603 → 240 根 1m K 线（09:31~15:00 A股完整交易时段）
   - 每根只含 `stime + close`（open/high/low/volume 字段 broker 不返或返 0.0）
2. 当前 `hq_history.fetch_bars()` 直接把 `period` 转发给 broker → broker 收到 `period=1d` 但实际能力是 1m
3. 上一轮加的 `his_hq_test_mode=1` mock 模式让回测能跑通，但**用户看出来的"行情与实际不符" = 100% 命中**，因为 mock 是合成数据
4. 架构上**broker 只返 1m close 是 stub 行为 + 真实 QMT broker 行为**（设计如此）→ strategy_exec 端必须自己做周期聚合

**用户硬规则**：
- 删 `his_hq_test_mode`（mock 模式作废）— **永远走实盘 broker**
- 不动 broker 端代码（xtquant / QMT Windows 端）— broker 是单源真相
- 改 strategy_exec 端：永远拉 1m，按用户要的 period 聚合 OHLCV

## What

### P0 — change 骨架

新建 `openspec/changes/2026-08-30-his-hq-aggregate-bars/`，proposal + tasks + spec-deltas/strategy-exec.md。

### P1 — strategy_exec 端实现（4 commits）

1. **commit 1: `hq_history.py` 删 mock 短路 + 强制 1m + 加聚合层**
   - 删 `_is_his_hq_mock_mode()` 函数
   - 删 `if _is_his_hq_mock_mode(): return generate_mock_bars(...)` 短路
   - `fetch_bars()` 内部：用户传 period → **永远发 `period='1m'` 给 broker** + `fields=['close']`
   - 拿到 1m close 数组 → **按用户 period 聚合**：
     - `1m` 直接返（无聚合）
     - `5m` 每 5 根 1m 聚合 OHLCV（open=第一根, close=最后一根, high=max, low=min, volume=sum）
     - `15m` / `30m` / `60m` 同上（N=15/30/60 根）
     - `1d` A股按交易日聚合：每根 1m `YYYYMMDDHHMMSS` → 同日 09:31~15:00 聚合 OHLCV
   - **A股交易日历**：周末跳过 + 09:30~11:30 / 13:00~15:00 交易时段识别
   - 新模块 `strategy_exec/market_data/aggregator.py`：纯函数 + 单测友好

2. **commit 2: 删 init_db seed + 删 sys_config 读**
   - 删 `server/infra/db.py` `_run_seed_cantrdstktypes_via_session` 里 `his_hq_test_mode` seed 段
   - 删 `server/main.py` 启动日志的 `his_hq_test_mode` 打印段
   - 删 `strategy_exec/strategy_exec/market_data/hq_history.py` 的 `from strategy_exec.data_access.sys_config import read as _read_sys_config` 引用
   - 删 `strategy_exec/strategy_exec/data_access/sys_config.py`（整个文件 — 不再需要，rpc_test_mode 是 server 端，与 strategy_exec 无关）
   - 删 `__init__.py` 任何引用（如有）

3. **commit 3: 删 mock_history.py**
   - 删 `strategy_exec/strategy_exec/market_data/mock_history.py`（旧版 mock 离线生成器，作废）
   - 删 `tests/strategy_exec/test_mock_history.py`（对应单测）
   - 删 `tests/strategy_exec/test_sys_config_cache.py`（sys_config 读单测作废）
   - 删 `server/tests/strategy/test_stale_queued_cleanup.py`（cleanup endpoint 与本 change 冲突 — 上一轮 add mock 时加的）
   - 删 `server/api/script_strategy/strategies.py` 的 `stale_queued_cleanup_endpoint` + `mark_stale_queued_failed` helper
   - **注**：list_stale_queued_tasks + GET `/stale-queued` 端点**保留**（仅 GET 不改数据，可继续用于 admin 监控）
   - 删 `server/services/script_strategy/batches.py` 的 `mark_stale_queued_failed` + `STALE_CLEANUP_ERROR_MSG`
   - 删 `server/services/script_strategy/__init__.py` 的 `mark_stale_queued_failed` / `STALE_CLEANUP_ERROR_MSG` export

4. **commit 4: 端到端验收**
   - 重启 strategy_exec
   - 提交一个回测 (admin token + sid=12 single)
   - 验证：fetch_his_bars 走真 broker 1m + strategy_exec 聚合到 1d
   - 日志确认：broker `period=1m` 请求、收到 240 根/天、聚合到 N 个 1d K 线
   - DB 写 status='finished' + pnl/trades_count 有值

### P2 — 单测 (1 commit)

5. **commit 5: aggregator 单测 + 清理 mock 残留**
   - 新 `tests/strategy_exec/test_aggregator.py`：
     - 1m 透传（无聚合）
     - 5m / 15m / 30m / 60m 聚合 OHLCV 正确
     - 1d A股聚合：周末跳过 / 09:30~11:30 + 13:00~15:00 时段
     - 边界：当日不足 N 根（早盘前 09:30 缺数据）/ 跨日 stime 解析
   - 跑全基线 `pytest server/tests/ tests/strategy_exec/` → 守住 142 passed 退化为 ~125-130 passed（删了 25 个 mock/cleanup 单测 + 加 ~10 个 aggregator）

### P3 — 文档 + 归档 (2 commits)

6. **commit 6: spec-delta merge + 归档 change**
   - `openspec/specs/strategy-exec/spec.md`：
     - **删 REQ-SE-013**（his_hq_test_mode mock 模式）整段
     - **改 REQ-SE-012**（broker his_hq）→ 新合约：
       - broker his_hq **永远**收 `period='1m' fields=['close']`
       - strategy_exec 端按用户 period 聚合（1m / 5m / 15m / 30m / 60m / 1d）
       - 1d 聚合按 A股交易日历（周末跳过、交易时段识别）
   - 删 spec 里的 cleanup endpoint 段
   - 归档 `mv openspec/changes/2026-08-30-his-hq-aggregate-bars openspec/changes/archive/`

7. **commit 7: 知识库同步**
   - 改 `知识库/策略服务/历史行情.md`：删 mock 模式段，写"1m 拉 + 聚合"流程
   - 改 `知识库/策略服务/架构概览.md`：删 mock_history 引用
   - 改 `strategy_exec/README.md`：删"离线开发模式"段
   - 删 `server/infra/db.py` 注释里 `his_hq_test_mode` 引用

## 不做什么

- **不动 broker 端代码**（`iquant/quota_his.py`）— broker 是单源真相
- **不动 EvTrade server 端**（除清理 cleanup endpoint / init_db seed）
- **不动 RPC 测试模式**（`rpc_test_mode`）— 它是 server 端 RPC mock，与 strategy_exec 无关
- **不动 MySQL schema**
- **不动策略算法**（run_backtest / sweep 逻辑不变）
- **不动 Backtrader 集成**（adaper / backtest.py）
- **不动前端**（页面无变化，前端继续看 status/progress 流转）

## 影响面

| 模块 | 影响 |
|---|---|
| `strategy_exec/strategy_exec/market_data/hq_history.py` | -30 行 (删 mock 短路) + +20 行 (1m 强制 + 聚合调用) = 净 -10 行 |
| `strategy_exec/strategy_exec/market_data/aggregator.py` | 新增 ~150 行 (纯函数) |
| `strategy_exec/strategy_exec/market_data/mock_history.py` | 删除 ~165 行 |
| `strategy_exec/strategy_exec/data_access/sys_config.py` | 删除 ~95 行 |
| `server/infra/db.py` | -10 行 (his_hq_test_mode seed) |
| `server/main.py` | -15 行 (启动日志) |
| `server/services/script_strategy/batches.py` | -30 行 (mark_stale_queued_failed) |
| `server/api/script_strategy/strategies.py` | -45 行 (cleanup endpoint) |
| `server/services/script_strategy/__init__.py` | -3 行 |
| `server/tests/strategy/test_stale_queued_cleanup.py` | 删 1 文件 (161 行) |
| `tests/strategy_exec/test_mock_history.py` | 删 1 文件 (150 行) |
| `tests/strategy_exec/test_sys_config_cache.py` | 删 1 文件 (110 行) |
| `tests/strategy_exec/test_aggregator.py` | 新增 ~120 行 |
| `openspec/specs/strategy-exec/spec.md` | -150 行 (删 REQ-SE-013) + 改 REQ-SE-012 (1m 聚合段) |
| `知识库/策略服务/历史行情.md` | 大幅改写 |
| `知识库/策略服务/架构概览.md` | -1 行 (mock_history 引用) |
| `strategy_exec/README.md` | -20 行 (离线开发模式段) |

净变化：~-700 行（删除 mock/mock_history/sys_config/cleanup） + ~+300 行（aggregator + spec + 知识库） = **-400 行**

## Commit 拆解 (v6)

```
1. feat(strategy-exec): hq_history 删 mock + 强制 1m + 调 aggregator
2. chore(strategy-exec + server): 删 init_db seed his_hq_test_mode + sys_config 模块 + 启动日志
3. chore: 删 mock_history + cleanup endpoint + 旧单测
4. feat: 端到端验收 (手动 admin token + curl 跑通, commit 留 trace)
5. test(strategy-exec): aggregator 单测 (OHLCV / A股交易日历 / 边界)
6. docs(openspec): strategy-exec REQ-SE-012 改写 + REQ-SE-013 删 + 归档
7. docs(knowledge): 历史行情.md + 架构概览 + README 同步
```

## 数据安全（用户硬规则 2026-08-27）

- [ ] 不动 MySQL schema
- [ ] 不 drop / truncate / delete from
- [ ] 不重建 schema
- [ ] cleanup endpoint 删除是**删 API**，不删 DB 数据（已标 failed 的老 queued 行保留）
- [ ] 不动 strategy_task 表数据

## 验收 (v6 完成自查)

- [ ] pytest strategy_exec/strategy_exec/tests/ → 0 fail (新 aggregator 单测)
- [ ] pytest server/tests/ + tests/strategy_exec/ → 守住基线 (142 - 25 mock/cleanup + 10 aggregator ≈ 127 passed)
- [ ] 端到端实测 (commit 4 留 trace): admin 提交回测 → strategy_exec 调 broker period=1m → 收到 1m close → aggregator 合成 1d OHLCV → run_backtest 跑完 → status='finished' + pnl 有值
- [ ] cd client && npm run build → 无报错 (前端无改动)
- [ ] git diff --stat 每 commit 单目的
- [ ] init_db seed 不再写 his_hq_test_mode (兼容: 重跑 init_db 不报错)
- [ ] his_hq_test_mode sys_config 行被忽略 (旧值保留, 不强删)