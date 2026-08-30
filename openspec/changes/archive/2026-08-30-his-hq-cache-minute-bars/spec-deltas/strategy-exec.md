# strategy-exec — Spec Delta (2026-08-30)

## 修改类型
MODIFIED — REQ-SE-012-broker-1m-aggregate 加 Cache 段 + 新 REQ: minute_bars cache 集成

## 变更内容

### § REQ-SE-012-broker-1m-aggregate 补 Cache (minute_bars) 子节

**Why** (2026-08-30 用户拍板):
- 历史行情太慢 (broker 单次 30s 超时 + 长区间 fetch 慢)
- minute_bars 表已存在 (his-quote-backfill 2026-08-30 加的, 174,240 条记录) 但 strategy_exec 没用
- 用户诉求: 每次回测**先查表, 不存在才调 broker**, 存在直接读
- 修 "backtest exception: bars 数据缺 'open' 列" 报错

#### 数据流 (cache 开启)

```
fetch_bars(stock, start, end, user_period, fields):
  ├─ 1. cache 查 (新):
  │    cached_bars = await query_minute_bars(stock, start, end)
  │    covered_days = unique(stime[:8] for b in cached_bars)  # 实际覆盖天数
  │    total_days = (end - start).days + 1
  │    log: "[hq_history] cache hit: stock=X coverage=N/M days, missing: K chunks"
  │
  ├─ 2. 拆 chunk (与原行为一致):
  │    chunks = _iter_chunks(start, end, chunk_days=10)
  │
  ├─ 3. case A — 完全覆盖 (covered_days == total_days):
  │    返 cached_bars (不走 broker, 不写回)
  │
  ├─ 4. case B — 部分覆盖 (0 < covered_days < total_days):
  │    missing_chunks = [c for c in chunks if c 日期不在 covered_days]
  │    broker_bars = []
  │    for c in missing_chunks:
  │      bars_i = await _fetch_one_chunk(stock, c.start, c.end, period)
  │      broker_bars.extend(bars_i)
  │      await upsert_minute_bars(stock, bars_i)  # 写回 cache
  │    all_bars = cached_bars + broker_bars
  │
  ├─ 5. case C — 无覆盖 (covered_days == 0):
  │    broker_bars = await _fetch_one_chunk(stock, start, end, period)
  │    await upsert_minute_bars(stock, broker_bars)  # 写回 cache
  │    all_bars = broker_bars
  │
  ├─ 6. 拼凑 + sort by stime
  └─ 7. 调 aggregator (1m 透传 / 5m/15m/... / 1d)
```

#### 新配置 (2026-08-30)

| 字段 | 默认 | env override |
|------|------|--------------|
| `his_hq_cache_enabled` | True | `EVTRADE_HIS_HQ_CACHE_ENABLED=1` |

#### 新 helper (strategy_exec/data_access/minute_bars.py)

```python
async def query_minute_bars(stock_code: str, start_date: str, end_date: str) -> List[Dict]:
    """查 minute_bars 表, 返 [stime, open, close, high, low, avg_price, volume]
    错误/不存在 → 返 [], 不抛
    async 包装: 内部用 asyncio.to_thread 跑 sync sqlalchemy
    """

async def upsert_minute_bars(stock_code: str, bars: List[Dict]) -> int:
    """批量 upsert (executemany + ON DUPLICATE KEY UPDATE, 幂等)
    复用 scripts/fetch_minute_bars.py 的 upsert 函数
    返写入条数
    """
```

#### Scenario: 1d period, 区间全在 cache

- **GIVEN** minute_bars 已 1m 缓存 20250101-20250601
- **WHEN** user POST `/internal/run-task` with `start_date=20250101 end_date=20250601 period=1d`
- **THEN** query_minute_bars 返 ~200 交易日 × 240 1m = ~48000 bars
- **AND** covered_days = 实际交易日数 (匹配 total_days)
- **AND** **不走 broker**, 拼凑 + sort + 调 aggregator
- **AND** aggregator 1d 聚合 → ~200 根 1d K 线
- **AND** run_backtest 跑完 (broker 调用时间 0s)

#### Scenario: 部分覆盖

- **GIVEN** minute_bars 已缓存 20250101-20250228, 未缓存 20250301-20250331
- **WHEN** user fetch 20250101-20250331
- **THEN** covered_days = 实际缓存天数 (e.g. 41 天)
- **AND** missing_chunks = [20250228-20250309, 20250310-20250319, 20250320-20250329, 20250330-20250331] (4 段)
- **AND** broker 4 段串行调 → ~4800 bars
- **AND** upsert_minute_bars 写回 → 下次覆盖
- **AND** 拼凑后返 ~6600 bars

#### Scenario: 无覆盖

- **GIVEN** minute_bars 空 (新标的, 未采集过)
- **WHEN** user fetch 任意区间
- **THEN** covered_days = 0 → case C
- **AND** broker 全区间 fetch + upsert
- **AND** 下次相同区间 → case A (cache hit)

#### Scenario: cache 关闭 (向后兼容)

- **GIVEN** `his_hq_cache_enabled=False` (env `EVTRADE_HIS_HQ_CACHE_ENABLED=0`)
- **WHEN** strategy_exec 调 fetch_bars
- **THEN** 保留原行为: chunked fetch broker, 不查 cache, 不写回
- **AND** 与 fetch_minute_bars.py CLI 一致

### § REQ: aggregator 兜底 (修"缺 open 列"报错, 2026-08-30)

**Why**:
- broker stub 不返 OHLV (close=0 占位)
- aggregator _aggregate_one_bucket 用 broker 字段, 但 broker 返 '0.0' 时被当合法值 → Backtrader 算 NaN
- _make_pandas_data_feed `if "open" not in df.columns: raise` → Backtrader 计算失败

#### 修法 (2026-08-30)

1. `aggregator._aggregate_one_bucket`:
   - 加 `_safe_to_float(v, default=None)` helper
   - broker 返 '0.0' 或 None → 跳过该字段, fallback close
   - **不再保留 broker '0.0' 占位** (避免 Backtrader NaN)

2. `backtest._make_pandas_data_feed`:
   - `if "open" not in df.columns: raise` 改为: 若 open 列全 NaN → 用 close 列填充
   - 若 close 列全 NaN → raise ValueError (保留原报错, 但极少见)
   - log warning `[backtest] bars N 根 open 为 NaN, 用 close 兜底`

#### Scenario: broker stub close=0

- **GIVEN** broker 返 1m bars 只有 stime + close (其他 OHLV=None 或 0)
- **WHEN** aggregator 1d 聚合
- **THEN** _aggregate_one_bucket: broker 字段 None/0 → 跳过, fallback close
- **AND** 1d bars: open=high=low=close (兜底), volume=0
- **AND** _make_pandas_data_feed: open NaN → 用 close 填充 (无 raise)
- **AND** Backtrader 计算指标 (e.g. SMA) 用 close 数据

#### Scenario: 真 broker (xtquant) 返完整 OHLCV

- **GIVEN** broker 返 1m bars 完整 OHLCV
- **WHEN** aggregator 1d 聚合
- **THEN** 用 broker 真实 OHLV (非 0, 非 None)
- **AND** 1d bars: open=first_1m_open, high=max, low=min, close=last_1m_close
- **AND** aggregator 不触发 close 兜底

#### Scenario: 极端 — close 也全 0

- **GIVEN** broker stub 完全没数据 (close=0, open=0, high=0, low=0, volume=0)
- **WHEN** _make_pandas_data_feed
- **THEN** close 列全 NaN (after pd.to_numeric coerce) → raise ValueError (保留原报错)
- **AND** run_backtest failed (与原行为一致)

## 影响面

| 模块 | 影响 |
|---|---|
| `strategy_exec/strategy_exec/data_access/minute_bars.py` | 新增 ~80 行 |
| `strategy_exec/strategy_exec/market_data/hq_history.py` | +30 行 (cache 逻辑) |
| `strategy_exec/strategy_exec/market_data/aggregator.py` | +10 行 (close 兜底) |
| `strategy_exec/strategy_exec/engines/backtrader/backtest.py` | +10 行 (NaN 兜底) |
| `strategy_exec/strategy_exec/config.py` | +1 字段 |
| `tests/strategy_exec/test_minute_bars_cache.py` | 新增 ~120 行 |
| `tests/strategy_exec/test_aggregator_fallback.py` | 新增 ~80 行 |
| `openspec/specs/strategy-exec/spec.md` | +30 行 |
| `openspec/specs/his-quote-backfill/spec.md` | +15 行 |
| `知识库/策略服务/历史行情.md` | +30 行 |
| `知识库/后端服务/数据补全/行情同步补全.md` | +15 行 |
| `strategy_exec/README.md` | +10 行 |

净变化: ~+430 行

## 不修改

- 不动 broker 端 (`iquant/quota_his.py`) - broker 单源真相
- 不动 MySQL schema (minute_bars 已存在)
- 不动 quote_sync 服务 (已能批量 upsert)
- 不动 his-quote-backfill spec (仅加 strategy_exec 集成段)
- 不动前端 (无变化)
- 不改 aggregator 1m 透传逻辑 (仅修 _aggregate_one_bucket 兜底)