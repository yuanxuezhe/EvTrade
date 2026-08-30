# His-HQ Cache Minute-Bars — 回测前查 minute_bars 表 + 缺时拉 broker (2026-08-30)

> 用户拍板 2026-08-30：
> 1. 历史行情太慢 — 加 minute_bars 表缓存（精度 1m，主键 stock_code+stime，字段 open/close/high/low/均价/交易量）
> 2. 每次回测**先查表，不存在才调 broker**，存在直接读
> 3. 修 "backtest exception: bars 数据缺 'open' 列"（broker stub close=0 → aggregator 兜底 → Backtrader 报缺 open 列）

## Why

**实测 (2026-08-30)**：

```
sid=12 backtest 20250603~20250605 period=1d
→ broker 720 1m raw bars (broker stub 30 天返 18/22 天, close=0 全 0)
→ aggregator 3 1d bars (close=0)
→ run_backtest failed 'bars 数据缺 open 列' / 'array assignment index out of range'
```

**minute_bars 表已存在**（his-quote-backfill change 2026-08-30 加的，174,240 条记录）：
- 主键 `(stock_code, stime)` 14位 YYYYMMDDHHMMSS
- 字段：`open / close / high / low / avg_price / volume`
- 有 `scripts/fetch_minute_bars.py` 批量 upsert 工具
- 但 strategy_exec 端**没集成**：每次回测都走 broker → 慢

**用户两个诉求**：
1. **建表缓存**（已有 minute_bars，差 strategy_exec 集成）
2. **修 "缺 open 列"**（broker stub close=0 + aggregator 兜底逻辑漏洞 → Backtrader 报错）

## What

### P0 — change 骨架

`openspec/changes/2026-08-30-his-hq-cache-minute-bars/` (proposal + tasks + spec-deltas/strategy-exec.md)。

### P1 — strategy_exec 端 cache 集成 + 修聚合 (5 commits)

1. **commit 1 — minute_bars 读 helper (`strategy_exec/data_access/minute_bars.py`)**
   - 新增 `query_minute_bars(stock_code, start_date, end_date) -> List[Dict]`
   - 直连 MySQL (复用 EVTRADE_DB_URL)
   - SQL: `SELECT stock_code, stime, open, close, high, low, avg_price, volume FROM minute_bars WHERE stock_code=? AND stime BETWEEN ? AND ? ORDER BY stime ASC`
   - 返 list of dict，stime 14位
   - 错误 / 不存在 → 返 []，不抛
   - 跨进程可调用：async 包装 (内部用 asyncio.to_thread 跑 sync sqlalchemy)

2. **commit 2 — minute_bars 写 helper (复用 fetch_minute_bars.upsert)**
   - `strategy_exec/data_access/minute_bars.py` 加 `upsert_minute_bars(stock_code, bars) -> int`
   - 内部调 server/services/quote_sync/repository.py 的 upsert 函数（已有）
   - 复用 broker raw bars → 落地 minute_bars（avg_price=amount/volume VWAP）
   - 用 `asyncio.to_thread` 包 sync DB IO

3. **commit 3 — hq_history fetch_bars 加 cache 逻辑**
   - `fetch_bars()` 入口改：
     ```
     1. 先 query_minute_bars(stock, start, end) → cached_bars
     2. 找到 cached_bars 覆盖的天数 = X
     3. if X == total_days: 直接返 cached_bars (不走 broker)
     4. if X > 0 且 X < total_days: 缺的段走 chunked fetch + upsert 到 minute_bars
     5. if X == 0: 全走 chunked fetch + upsert
     6. 全部 cached + broker 拼成完整 List[Dict] 后 sort by stime
     ```
   - 配置开关：`his_hq_cache_enabled: bool = Field(default=True)`
   - 关闭时回退原行为（与 fetch_minute_bars 一致）
   - debug log: `[hq_history] cache hit: stock=X coverage=18/22 days, missing: 4 chunks`

4. **commit 4 — 修 "缺 open 列" 报错**
   - `strategy_exec/market_data/aggregator.py` _aggregate_one_bucket:
     - broker 不返 OHLV 字段时，**强制 close 兜底 open/high/low**（不保留 broker 返的 '0.0' 占位）
     - 加 `_safe_to_float(v, default=None) -> float | None` helper
     - 当 broker 返 '0.0' 或 None → 跳过该字段, fallback close
   - `strategy_exec/engines/backtrader/backtest.py` _make_pandas_data_feed:
     - `if "open" not in df.columns: raise` 改为: 若 open 列全 NaN → 用 close 列填充
     - 若 close 列全 NaN → raise ValueError (保留原报错)
     - 加 df.dropna(subset=["open","close"], how="all") 过滤纯 NaN K 线
     - log warning `[backtest] bars N 根 open 为 NaN, 用 close 兜底` (透明处理, 让 run_backtest 不报"缺 open 列")

5. **commit 5 — 端到端验收 (1 年回测走 cache)**
   - 先看 minute_bars 是否有 600519.SH / 159992.SZ 数据（his-quote-backfill 已采）
   - 提交 sid=12 backtest 20250101-20251231 period=1d
   - 验证:
     - fetch_bars cache hit（broker 不调或只调缺的）
     - 1d 聚合后 bars open=close (兜底), 跑通 Backtrader
     - run_backtest status=finished
   - 留 trace 在 commit message

### P2 — 单测 (2 commits)

6. **commit 6 — minute_bars read 单测 (mock DB)**
   - `tests/strategy_exec/test_minute_bars_cache.py`:
     - query_minute_bars: 空 / 满 / 部分覆盖 / 跨段
     - upsert_minute_bars: 正常写入 / 重复 upsert 幂等 / 空 list 跳过
     - fetch_bars cache 集成:
       - 全覆盖 → 不调 broker (mock _fetch_one_chunk 失败如被调)
       - 部分覆盖 → 只调缺的段
       - 无覆盖 → 调全部段
       - cache 关闭 → 调全部段 (向后兼容)
   - 验证基线: `pytest server/tests/ + tests/strategy_exec/` 守住 146+

7. **commit 7 — aggregator / _make_pandas_data_feed 兜底单测**
   - `tests/strategy_exec/test_aggregator_fallback.py`:
     - broker 不返 OHLV → aggregator 用 close 兜底
     - broker 返 '0.0' → aggregator 跳过, 用 close
     - _make_pandas_data_feed: open NaN 用 close 填充
     - close 全 NaN → raise (保留原报错)

### P3 — 文档 + 归档 (2 commits)

8. **commit 8 — spec-delta merge + 归档**
   - 改 `openspec/specs/strategy-exec/spec.md`:
     - REQ-SE-012-broker-1m-aggregate 加 cache 段
     - 新 REQ: minute_bars cache (回测前查 → 缺时拉 broker → 写表)
   - 改 `openspec/specs/his-quote-backfill/spec.md` (轻量):
     - 加"strategy_exec 集成 cache"段 (回测前查 minute_bars)
   - 归档: `mv openspec/changes/2026-08-30-his-hq-cache-minute-bars openspec/changes/archive/`

9. **commit 9 — 知识库同步**
   - 改 `知识库/策略服务/历史行情.md`:
     - 加"Cache (minute_bars)" 段 (回测前查 → 缺时拉 → 写表)
   - 改 `知识库/后端服务/数据补全/行情同步补全.md`:
     - 加"strategy_exec 集成"段
   - 改 `strategy_exec/README.md`:
     - 加"minute_bars cache"段

## 不做什么

- **不动 broker 端** (`iquant/quota_his.py`) - broker 单源真相
- **不动 MySQL schema** - minute_bars 表已存在
- **不动 quote_sync 服务** (`server/services/quote_sync/`) - 已能批量 upsert
- **不动 his-quote-backfill spec** - 仅加 strategy_exec 集成段
- **不动前端** - 无变化
- **不改 aggregator 1m 透传逻辑** - 仅修 _aggregate_one_bucket 兜底

## 影响面

| 模块 | 影响 |
|---|---|
| `strategy_exec/strategy_exec/data_access/minute_bars.py` | 新增 ~80 行 (read + write helper) |
| `strategy_exec/strategy_exec/market_data/hq_history.py` | +30 行 (cache 逻辑) |
| `strategy_exec/strategy_exec/market_data/aggregator.py` | +10 行 (close 兜底) |
| `strategy_exec/strategy_exec/engines/backtrader/backtest.py` | +10 行 (NaN 兜底) |
| `strategy_exec/strategy_exec/config.py` | +1 字段 (his_hq_cache_enabled) |
| `tests/strategy_exec/test_minute_bars_cache.py` | 新增 ~120 行 |
| `tests/strategy_exec/test_aggregator_fallback.py` | 新增 ~80 行 |
| `openspec/specs/strategy-exec/spec.md` | +30 行 |
| `openspec/specs/his-quote-backfill/spec.md` | +15 行 |
| `知识库/策略服务/历史行情.md` | +30 行 |
| `知识库/后端服务/数据补全/行情同步补全.md` | +15 行 |
| `strategy_exec/README.md` | +10 行 |

净变化: ~+430 行

## Commit 拆解 (v6)

```
1. feat(strategy-exec): minute_bars 读 helper (query_minute_bars)
2. feat(strategy-exec): minute_bars 写 helper (upsert_minute_bars)
3. feat(strategy-exec): hq_history fetch_bars 加 cache 逻辑
4. fix(strategy-exec): aggregator + _make_pandas_data_feed 兜底修"缺 open 列"
5. test: 端到端验收 (1 年回测走 cache)
6. test(strategy-exec): minute_bars cache 单测 (8 cases)
7. test(strategy-exec): aggregator + pandas feed 兜底单测 (4 cases)
8. docs(openspec): spec-delta merge + 归档
9. docs(knowledge): 历史行情 + 行情同步补全 + README 同步
```

## 数据安全（用户硬规则 2026-08-27）

- [ ] 不动 MySQL schema
- [ ] 不 drop / truncate / delete from
- [ ] 不重建 schema
- [ ] minute_bars 仅 INSERT/UPDATE (upsert 幂等, 不删行)
- [ ] 不动 strategy_task 数据

## 验收 (v6 完成自查)

- [ ] pytest tests/strategy_exec/test_minute_bars_cache.py → 0 fail (8 cases)
- [ ] pytest tests/strategy_exec/test_aggregator_fallback.py → 0 fail (4 cases)
- [ ] pytest server/tests/ + tests/strategy_exec/ → 守住 146+ (新加 12 = 158)
- [ ] 端到端实测: 1 年回测 cache hit, run_backtest finished
- [ ] git diff --stat 每 commit 单目的
- [ ] 外部接口 fetch_bars(stock, start, end, period, fields) 不变
- [ ] aggregator + strategy_exec 集成正常