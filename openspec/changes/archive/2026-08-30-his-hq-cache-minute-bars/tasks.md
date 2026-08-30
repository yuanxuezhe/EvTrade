# Tasks: his-hq-cache-minute-bars (2026-08-30)

> 每个 task = 1 个 commit（v6 单 commit 单目的）。
> 整体按 P0→P1→P2→P3 顺序推进。

## P0 — change 骨架

- [ ] **commit 0 (骨架)** — proposal + tasks + spec-deltas 已创建

## P1 — strategy_exec 端 cache 集成 + 修聚合

- [ ] **commit 1 — minute_bars 读 helper**
  - 新增 `strategy_exec/strategy_exec/data_access/minute_bars.py`:
    - `query_minute_bars(stock_code, start_date, end_date) -> List[Dict]`
    - 直连 MySQL (复用 EVTRADE_DB_URL)
    - SQL: `SELECT stock_code, stime, open, close, high, low, avg_price, volume FROM minute_bars WHERE stock_code=? AND stime BETWEEN ? AND ? ORDER BY stime ASC`
    - 返 list of dict, stime 14位
    - 错误 / 不存在 → 返 [], 不抛
    - 跨进程可调用: async 包装 + asyncio.to_thread

- [ ] **commit 2 — minute_bars 写 helper**
  - 复用 `scripts/fetch_minute_bars.py` 的 upsert 函数
  - `strategy_exec/data_access/minute_bars.py` 加 `upsert_minute_bars(stock_code, bars) -> int`
  - 内部调 upsert (executemany + ON DUPLICATE KEY UPDATE, 幂等)
  - 用 asyncio.to_thread 包 sync DB IO
  - broker raw bars → minute_bars 行 (avg_price=amount/volume)

- [ ] **commit 3 — hq_history fetch_bars 加 cache 逻辑**
  - `fetch_bars()` 入口改:
    ```
    1. 先 query_minute_bars(stock, start, end) → cached_bars
    2. 找到 cached_bars 覆盖的天数 = X (按 stime[:8] 去重)
    3. if X == total_days: 直接返 cached_bars (不走 broker)
    4. if X > 0 且 X < total_days: 缺的段走 chunked fetch + upsert 到 minute_bars
    5. if X == 0: 全走 chunked fetch + upsert
    6. 全部 cached + broker 拼成完整 List[Dict] 后 sort by stime
    ```
  - 配置开关 `his_hq_cache_enabled: bool = Field(default=True)` (env override `EVTRADE_HIS_HQ_CACHE_ENABLED=1`)
  - 关闭时回退原行为
  - debug log: `[hq_history] cache hit: stock=X coverage=18/22 days, missing: 4 chunks`

- [ ] **commit 4 — 修 "缺 open 列" 报错 (aggregator + pandas feed)**
  - `strategy_exec/market_data/aggregator.py` _aggregate_one_bucket:
    - 加 `_safe_to_float(v, default=None) -> float | None` helper
    - broker 返 '0.0' 或 None → 跳过该字段, fallback close
    - 不再保留 broker '0.0' 占位 (避免 Backtrader 算 NaN)
  - `strategy_exec/engines/backtrader/backtest.py` _make_pandas_data_feed:
    - `if "open" not in df.columns: raise` 改为: 若 open 列全 NaN → 用 close 列填充
    - 若 close 列全 NaN → raise (保留原报错)
    - log warning `[backtest] bars N 根 open 为 NaN, 用 close 兜底`

- [ ] **commit 5 — 端到端验收 (1 年回测走 cache)**
  - 检查 minute_bars 是否已有 600519.SH / 159992.SZ 数据
  - 提交 sid=12 backtest 20250101-20251231 period=1d
  - 验证:
    - fetch_bars cache hit (broker 不调或只调缺的)
    - 1d 聚合后 bars open=close (兜底)
    - run_backtest status=finished

## P2 — 单测

- [ ] **commit 6 — minute_bars cache 单测 (8 cases)**
  - `tests/strategy_exec/test_minute_bars_cache.py`:
    - query_minute_bars: 空 / 满 / 部分覆盖 / 跨段
    - upsert_minute_bars: 正常写入 / 重复 upsert 幂等 / 空 list 跳过
    - fetch_bars cache 集成:
      - 全覆盖 → 不调 broker
      - 部分覆盖 → 只调缺的段
      - 无覆盖 → 调全部段
      - cache 关闭 → 调全部段

- [ ] **commit 7 — aggregator / pandas feed 兜底单测 (4 cases)**
  - `tests/strategy_exec/test_aggregator_fallback.py`:
    - broker 不返 OHLV → aggregator 用 close 兜底
    - broker 返 '0.0' → aggregator 跳过, 用 close
    - _make_pandas_data_feed: open NaN 用 close 填充
    - close 全 NaN → raise

## P3 — 文档 + 归档

- [ ] **commit 8 — spec-delta merge + 归档**
  - 改 `openspec/specs/strategy-exec/spec.md`:
    - REQ-SE-012-broker-1m-aggregate 加 cache 段
    - 新 REQ: minute_bars cache (回测前查 → 缺时拉 broker → 写表)
  - 改 `openspec/specs/his-quote-backfill/spec.md` (轻量):
    - 加 "strategy_exec 集成 cache" 段
  - 归档: `mv openspec/changes/2026-08-30-his-hq-cache-minute-bars openspec/changes/archive/`

- [ ] **commit 9 — 知识库同步**
  - 改 `知识库/策略服务/历史行情.md`:
    - 加 "Cache (minute_bars)" 段
  - 改 `知识库/后端服务/数据补全/行情同步补全.md`:
    - 加 "strategy_exec 集成" 段
  - 改 `strategy_exec/README.md`:
    - 加 "minute_bars cache" 段

## 验证 (v6 完成自查)

- [ ] pytest tests/strategy_exec/test_minute_bars_cache.py → 0 fail (8 cases)
- [ ] pytest tests/strategy_exec/test_aggregator_fallback.py → 0 fail (4 cases)
- [ ] pytest server/tests/ + tests/strategy_exec/ → 守住 (158 passed)
- [ ] 端到端实测: 1 年回测 cache hit, run_backtest finished
- [ ] git diff --stat 每 commit 单目的
- [ ] 外部接口 fetch_bars 不变
- [ ] aggregator + pandas feed 集成正常