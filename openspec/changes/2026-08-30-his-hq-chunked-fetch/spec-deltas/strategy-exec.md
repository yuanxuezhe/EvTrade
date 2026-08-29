# strategy-exec — Spec Delta (2026-08-30)

## 修改类型
MODIFIED — REQ-SE-012-broker-1m-aggregate 段补 chunked fetch 子节

## 变更内容

### § REQ-SE-012-broker-1m-aggregate 补 Chunked Fetch 子节

**Why** (2026-08-30 用户拍板):
- 长区间回测 (30 天/1 年) broker 单次 fetch 30s 超时 (`evtrade_his_hq_req_timeout=30`)
- 实测 30 天 33.7s (broker stub 触发边界); 真实生产 broker 数据量更大必超时
- 用户要求: **拆 10 天/批, 全部取到后拼成完整 K 线**
- 不能用 mock 兜底 (用户硬规则: 永远走实盘 broker)

#### 新配置 (2026-08-30)

| 字段 | 默认 | 范围 | env override |
|------|------|------|--------------|
| `his_hq_chunk_days` | 10 | 1-30 | `EVTRADE_HIS_HQ_CHUNK_DAYS=10` |
| `his_hq_chunk_enabled` | True | bool | `EVTRADE_HIS_HQ_CHUNK_ENABLED=1` |

#### 数据流 (chunked 模式)

```
fetch_bars(stock, start, end, user_period, fields):
  ├─ 1. 拆分: [start, end] → N 段 (每段 ≤ chunk_days=10)
  │    └─ _iter_chunks("20250101", "20250130", 10) → [
  │         ("20250101", "20250110"),
  │         ("20250111", "20250120"),
  │         ("20250121", "20250130")
  │       ]
  ├─ 2. 串行调 broker (每段独立 30s 超时):
  │    for cs, ce in chunks:
  │      bars_i = await _fetch_one_chunk(stock, cs, ce, period)
  │    └─ 任一段 raise → 立即 raise HQHistoryError (不返部分数据)
  ├─ 3. 拼凑 + sort by stime
  │    └─ all_bars = sorted(bars_1 + bars_2 + ... + bars_N, key=lambda b: b['stime'])
  └─ 4. 调 aggregator (1m 透传 / 5m/15m/... / 1d)
       └─ 与原行为一致
```

#### _iter_chunks 纯函数 (boundary 规则)

- 段大小 = `chunk_days` (默认 10)
- **每段** 起始日 = `start + i * chunk_days`, 结束日 = `min(start + (i+1) * chunk_days - 1, end)`
- 末段可能 < `chunk_days` (不足 1 段完整 10 天)
- 单日区间 → 1 段
- 跨年正常处理 (e.g. 20241201-20250131 / chunk=30 → 2 段: [12-01, 12-30] + [12-31, 01-31])

#### Scenario: 30 天 1d 回测

- **GIVEN** user POST `/internal/run-task` with `start_date=20250101 end_date=20250130 period=1d`
- **WHEN** strategy_exec 调 `fetch_bars`
- **THEN** `his_hq_chunk_enabled=True` → 拆 3 段 (1-10, 11-20, 21-30)
- **AND** 串行调 broker 3 次, 每段独立 30s 超时
- **AND** broker stub 30 天返 18/22 天 (2025-01-01~30 节假日 + stub 不全), 仍 1m 数据 ≥ 4320 根
- **AND** aggregator 合成 1d → 18-20 个 1d K 线
- **AND** run_backtest 跑完

实测 2026-08-30: 30 天 33.7s (chunk 关闭时) / 期望 chunk 开启后每段 ~10s

#### Scenario: 1 年 1d 回测

- **GIVEN** start=20250101 end=20251231 period=1d
- **WHEN** strategy_exec 调 `fetch_bars`
- **THEN** 拆 37 段 (1-10, 11-20, ..., 12-21, 12-22, 12-23, 12-24, 12-25, 12-26, 12-27, 12-28, 12-29, 12-30, 12-31)
- **AND** 串行 37 次 broker fetch
- **AND** 全部成功 → 拼成 1 年 1m close (~200 交易日 × 240 ≈ 48000 根)
- **AND** aggregator → ~200 根 1d K 线

#### Scenario: chunked 关闭 (向后兼容)

- **GIVEN** `his_hq_chunk_enabled=False` (env `EVTRADE_HIS_HQ_CHUNK_ENABLED=0`)
- **WHEN** strategy_exec 调 `fetch_bars`
- **THEN** 保留原行为: 1 次 broker fetch 全区间
- **AND** 长区间 (≥30 天) 仍可能 30s 超时 → 502 (与原行为一致)

#### Scenario: 任一段失败

- **WHEN** 第 2 段 (20250111-20250120) broker 30s 超时
- **THEN** raise `HQHistoryError("chunked fetch failed at chunk 2 (20250111-20250120): ...")`
- **AND** 第 1 段已 fetch 的 bars **不返** (保持原子性)
- **AND** 上游 caller (run_backtest) 失败 → task status='failed'

#### Scenario: chunk_days=1 (退化)

- **GIVEN** `his_hq_chunk_days=1`
- **WHEN** 30 天 fetch
- **THEN** 拆 30 段 (1-1, 1-2, ..., 1-30)
- **AND** broker 30 次调用 (开销大, 仅作最保守退化)

#### 实测 (2026-08-30)

```text
chunk 关闭 (现状):
  30 days: 4320 bars, 33.7s (broker stub close=0)
  90 days: 13680 bars, 31.1s (broker stub close=0)

chunk 开启 (本 change 后):
  30 days: 3 chunks (1-10, 11-20, 21-30) → 期望 ~10s/段 = 30s 总
  1 year:  37 chunks → 期望 ~5min 总 (broker stub) / 实际 broker 可能更短
```

## 影响面

| 模块 | 影响 |
|---|---|
| `strategy_exec/strategy_exec/config.py` | +2 字段 (his_hq_chunk_days / his_hq_chunk_enabled) |
| `strategy_exec/strategy_exec/market_data/hq_history.py` | +40 行 (chunked fetch + _iter_chunks) |
| `tests/strategy_exec/test_hq_history_chunked.py` | 新增 ~80 行 |
| `openspec/specs/strategy-exec/spec.md` | +30 行 (chunked 段) |
| `知识库/策略服务/历史行情.md` | +30 行 (Chunked Fetch 段) |

净变化: ~+180 行 (轻量)

## 不修改

- 不动 broker 端 (`iquant/quota_his.py`) - broker 单源真相
- 不动 EvTrade server 端 - 与本 change 无关
- 不动 MySQL schema
- 不动 strategy 算法 (run_backtest / sweep)
- 不动 aggregator
- 不动前端
- 串行 fetch (不并发) - 用户原话"全部取到后拼凑", 并发可后续扩展

## 测试覆盖

- `tests/strategy_exec/test_hq_history_chunked.py` (7 cases):
  - _iter_chunks 纯函数 (5): 30天/31天/start==end/跨年/chunk=1 退化
  - chunked fetch 集成 (2): mock 多段拼凑 / 单段失败 raise
- 跑全基线 `pytest server/tests/ tests/strategy_exec/ -q` 守住 139+ 不退化