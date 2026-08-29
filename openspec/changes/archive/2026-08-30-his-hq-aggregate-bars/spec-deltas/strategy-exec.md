# strategy-exec — Spec Delta (2026-08-30)

## 修改类型
MODIFIED — 删 REQ-SE-013 + REQ-SE-014；改 REQ-SE-012 为"1m 拉 + strategy_exec 端聚合"

## 变更内容

### § 删 REQ-SE-013: broker his_hq 离线 mock 模式 (整段删除)

**原因**: 用户拍板 2026-08-30 — 删 `his_hq_test_mode` 参数；行情**永远**从 broker 拿 1m close，strategy_exec 端自己按 1m + 时间戳聚合其他周期。**无 mock 通道**，永远走实盘 broker。

涉及删除:
- `strategy_exec/strategy_exec/market_data/mock_history.py` (整个文件, ~165 行)
- `strategy_exec/strategy_exec/data_access/sys_config.py` (整个文件, ~95 行)
- `tests/strategy_exec/test_mock_history.py` (整个文件, ~150 行)
- `tests/strategy_exec/test_sys_config_cache.py` (整个文件, ~110 行)
- `server/infra/db.py` _run_seed_cantrdstktypes_via_session 的 his_hq_test_mode seed 段 (~10 行)
- `server/main.py` on_startup_rpc 的 his_hq_test_mode 启动日志 (~15 行)
- `openspec/specs/strategy-exec/spec.md` REQ-SE-013 整段

### § 删 REQ-SE-014: stale-queued cleanup (整段删除)

**原因**: 上一轮 add mock 时为清理老 queued 加的；现在 broker 永远走真链路，cleanup 不再需要。**保留** `GET /stale-queued` 端点（仅 admin 监控用，不改数据）。

涉及删除:
- `server/services/script_strategy/batches.py` 的 `mark_stale_queued_failed` + `STALE_CLEANUP_ERROR_MSG` (~30 行)
- `server/api/script_strategy/strategies.py` 的 `stale_queued_cleanup_endpoint` (~45 行)
- `server/services/script_strategy/__init__.py` 相关 export (~3 行)
- `server/tests/strategy/test_stale_queued_cleanup.py` (整个文件, ~161 行)

### § 改 REQ-SE-012: broker his_hq 数据流 (改写)

**Why**: broker 端 his_hq **只返 1m close**（用户实测确认）。当前 `fetch_bars()` 直接转发 `period` 给 broker 错误 — broker 实际只支持 1m。需要 strategy_exec 端按用户 period 自行聚合。

#### 新合约 (2026-08-30)

```
1. strategy_exec.market_data.hq_history.fetch_bars(
     stock_code, start_date, end_date, user_period, fields
   ):
     a. 内部固定用 period='1m' fields=['close'] 调 broker (broker 单源真相)
     b. 收到 1m bars 数组 (stime, close)
     c. 调 aggregator.aggregate_bars(bars, user_period)
     d. 返聚合后的 K 线
```

#### Aggregator 规则 (strategy_exec/market_data/aggregator.py 新模块)

| user_period | 聚合逻辑 | 输出 K 线数 |
|-------------|---------|-----------|
| `1m` | 透传 (无聚合) | 同 1m bars 数 |
| `5m` | 每 5 根 1m 聚合 1 根 (N=5):<br>open=第一根 close<br>high=max(close)<br>low=min(close)<br>volume=sum (broker 不返, 设 0) | 1m_bars / 5 (向下取整) |
| `15m` | N=15 | 1m_bars / 15 |
| `30m` | N=30 | 1m_bars / 30 |
| `60m` / `1h` | N=60 | 1m_bars / 60 |
| `1d` | 按 A股交易日历聚合 (周末跳过, 09:31~11:30 + 13:01~15:00 交易时段) | 实际交易日数 (跳过周末) |

**A股交易日历规则**:
- 周末 (Sat/Sun) 不生成 K 线
- 每日交易时段: 09:31~11:30 + 13:01~15:00
- 午休 (11:31~12:59) 不在 1m 数据中 (broker 自动跳过)
- 1d 聚合按 `stime[:8]` (YYYYMMDD) 分桶, 同日全聚合
- 边界: 半日 (e.g. 最后交易日 13:30 收盘) 仍按 1d 聚合

#### 数据 schema (聚合后)

```json
{
  "stime": "20250102" | "20250102093000" | "20250102133000",
  "open": 100.0,
  "high": 101.5,
  "low": 99.5,
  "close": 101.0,
  "volume": 0
}
```

- `stime` 格式: 1d → `YYYYMMDD` (8位, 对齐 broker 协议 + Backtrader `format="%Y%m%d%H%MSS"` 也能识别)
  - 实际上 Backtrader 当前用 `format="%Y%m%d%H%MSS"` 解析 — `1d` 的 stime 是 8位时需 padding `000000` 才能解析
  - **修复策略**: aggregator 1d 输出 `YYYYMMDD150000` (14位, 收盘时刻 15:00:00, 对齐 Backtrader 解析)
- `volume`: broker 1m close 不带 volume, aggregator **不造数据**, 输出 0 (与 broker 一致)

#### Scenario: 用户提交 1d period 回测

- **GIVEN** user POST `/api/script-strategy/strategies/12/backtest` with `period='1d'`, `start_date=20250101`, `end_date=20250110`
- **WHEN** strategy_exec 调 `fetch_his_bars`
- **THEN** 内部用 `period='1m' fields=['close']` 调 broker
- **AND** broker 返 5 天 × 240 根 1m close = 1200 根 1m bars
- **AND** aggregator 按 1d 聚合 → 5 个 1d bars (YYYYMMDD150000)
- **AND** run_backtest 正常完成 → DB `status='finished'`, pnl / trades_count / backtest_result 全有

#### Scenario: broker 不在线

- **WHEN** strategy_exec 调 broker 30s 超时 0 rows
- **THEN** raise `HQHistoryError` (BROKER_ERROR 502) — 与原行为一致
- **AND** 不再有任何 fallback（**无 mock**）

#### Scenario: 用户提交 5m period

- **WHEN** strategy_exec 调 `fetch_his_bars(..., period='5m')`
- **THEN** broker 仍返 1m close 1200 根
- **AND** aggregator 每 5 根聚合 1 根 → 240 根 5m bars
- **AND** 5m 聚合按时间桶 (5 根连续 1m → 1 根 5m)，不按自然小时

#### Scenario: 周末/节假日

- **WHEN** user request 跨周六周日
- **THEN** aggregator 1d 输出仅含交易日 (跳过 Sat/Sun)
- **AND** broker 1m 数据本身不含周末 (xtquant 自动跳过非交易日)

## 影响面

| 模块 | 影响 |
|---|---|
| `strategy_exec/strategy_exec/market_data/hq_history.py` | -30 +20 = 净 -10 行 |
| `strategy_exec/strategy_exec/market_data/aggregator.py` | 新增 ~150 行 (纯函数) |
| `strategy_exec/strategy_exec/market_data/mock_history.py` | 删 ~165 行 |
| `strategy_exec/strategy_exec/data_access/sys_config.py` | 删 ~95 行 |
| `server/infra/db.py` | -10 行 (his_hq_test_mode seed) |
| `server/main.py` | -15 行 (启动日志) |
| `server/services/script_strategy/batches.py` | -30 行 (mark_stale_queued_failed) |
| `server/api/script_strategy/strategies.py` | -45 行 (cleanup endpoint) |
| `server/services/script_strategy/__init__.py` | -3 行 |
| `server/tests/strategy/test_stale_queued_cleanup.py` | 删 1 文件 (161 行) |
| `tests/strategy_exec/test_mock_history.py` | 删 1 文件 (150 行) |
| `tests/strategy_exec/test_sys_config_cache.py` | 删 1 文件 (110 行) |
| `tests/strategy_exec/test_aggregator.py` | 新增 ~120 行 |
| `openspec/specs/strategy-exec/spec.md` | -150 + 改 REQ-SE-012 = 净 -50 行 |
| `知识库/策略服务/历史行情.md` | 大幅改写 |
| `知识库/策略服务/架构概览.md` | -1 行 (mock_history 引用) |
| `strategy_exec/README.md` | -20 行 (离线开发模式段) |

净变化: ~-400 行

## 不修改

- 不动 broker 端代码 (`iquant/quota_his.py`) - broker 是单源真相
- 不动 EvTrade server RPC 测试模式 (`rpc_test_mode`) - 是 server 端，与 strategy_exec 无关
- 不动 MySQL schema
- 不动策略算法 (run_backtest / sweep)
- 不动 Backtrader 集成
- 不动前端 (无变化)