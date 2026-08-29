# His-HQ Chunked Fetch — broker 长区间拆分 10 天/批 (2026-08-30)

> 用户拍板 2026-08-30：长区间回测（30 天/1 年）broker 单次 fetch 30s 超时，**拆成 10 天/批**调 broker，**全部取到后拼成完整 K 线**。

## Why

**实测 (2026-08-30)**：broker 单次 fetch 在 30 天 区间时：

```
[hq_history] stream idle, got 18/22 day replies (4320 rows) — some days may be holidays/missing data
30 days: 4320 bars, 33.7s
90 days: 13680 bars, 31.1s
```

- broker 单次 fetch 用满 30s 边界（`evtrade_his_hq_req_timeout: int = 30`，**配置 hard-coded**）
- broker 端**不严格按天返**（30天只返 18/22，stub 数据不完整）
- 真实生产 broker (xtquant) 数据量更大，**必超时** → 全部天返 0 → 502

**用户硬规则**：
- 拆 chunk（默认 10 天/批，与 `evtrade_his_hq_req_timeout=30s` 配合 — 10 天 ≤ 5-6s 安全）
- 全部取到后**后台拼凑**（不能用 mock 兜底）
- 不动 broker 端代码（broker 单源真相）
- 不动 MySQL schema / strategy_task 表

## What

### P0 — change 骨架

新建 `openspec/changes/2026-08-30-his-hq-chunked-fetch/`，proposal + tasks + spec-deltas/strategy-exec.md。

### P1 — strategy_exec 端 chunked fetch (2 commits)

1. **commit 1: config 加 `chunk_days` + hq_history 拆分调 broker**
   - `strategy_exec/strategy_exec/config.py`:
     - `his_hq_chunk_days: int = Field(default=10, ge=1, le=30)` — 单次 broker fetch 区间长度
     - `his_hq_chunk_enabled: bool = Field(default=True)` — 开关（关闭时回退原行为 1 次全拉）
   - `strategy_exec/strategy_exec/market_data/hq_history.py`:
     - `HQHistoryClient.fetch_bars()` 入口拆分：
       - 若 `his_hq_chunk_enabled` 关闭 → 保留原 1 次拉全区间
       - 若开启 → 把 `[start_date, end_date]` 拆成 N 段 (每段 ≤ `chunk_days` 天)，**串行**调 `_fetch_one_chunk(start, end, period)`
     - 每段独立 30s 超时（broker 端 idle timeout 不累加）
     - N 段全部成功后，**拼凑** 1 个 List[Dict] 返
     - 任一段失败 → raise `HQHistoryError("chunked fetch failed at chunk N (start=X, end=Y): ...")`，不返部分数据
   - 拆分工具：纯函数 `_iter_chunks(start, end, chunk_days) -> List[Tuple[str, str]]`
   - 配置 `EVTRADE_HIS_HQ_CHUNK_DAYS=10` / `EVTRADE_HIS_HQ_CHUNK_ENABLED=1` env override

2. **commit 2: chunked fetch 合并 + 外部接口兼容**
   - 拼凑按 stime 升序（broker stub 可能乱序）
   - 1d 聚合仍走 `aggregator.aggregate_bars()`（chunks 拼完后再聚合）
   - 外部接口签名 `fetch_bars(stock, start, end, period, fields)` **不变**（chunked 是内部实现）
   - 单元测试友好：fetch_bars 加可选参数 `_force_no_chunk: bool = False`（测试用，关闭 chunk 直接调 broker）
   - 加 debug log：`[hq_history] chunked fetch: 3 chunks (20250101-20250110, 20250111-20250120, 20250121-20250130)`

### P2 — 单测 (1 commit)

3. **commit 3: chunked 单测**
   - `tests/strategy_exec/test_hq_history_chunked.py`:
     - `_iter_chunks` 纯函数: 30 天 / chunk=10 → 3 段 (1-10, 11-20, 21-30)
     - 边界: 31 天 / chunk=10 → 4 段 (1-10, 11-20, 21-30, 31-31)
     - 边界: start == end / chunk=10 → 1 段 (1-1)
     - 跨年: 20241201-20250131 / chunk=30 → 2 段
     - chunk_days=1 时退化为"每天 1 段"
     - chunked fetch 拼接: mock 2 段 fetch → 返合并后 bars
     - 任一段失败 → raise (不返部分数据)
     - 单段超时 → raise (单 broker 超时)
   - 验证基线: `pytest server/tests/ tests/strategy_exec/ -q` 守住 139+ 不退化

### P3 — 端到端 + 文档 (2 commits)

4. **commit 4: 端到端验收 (1 年 backtest)**
   - 提交 sid=12 single backtest 1 年 (20250101-20251231) period=1d
   - 验证:
     - strategy_exec 日志显示 N 段 chunked fetch
     - broker 单段 fetch 都成功 (broker stub 应 1-2s/段)
     - 全部 chunk 拼成完整 1d K 线
     - run_backtest 正常完成 → status=finished (或 failed if broker stub 仍有问题，预期)

5. **commit 5: spec-delta merge + 归档 + 知识库**
   - 改 `openspec/specs/strategy-exec/spec.md`:
     - REQ-SE-012-broker-1m-aggregate 增加 "chunked fetch" 段
     - 新增参数 `his_hq_chunk_days=10` / `his_hq_chunk_enabled=True`
   - 归档 `mv openspec/changes/2026-08-30-his-hq-chunked-fetch openspec/changes/archive/`
   - 改 `知识库/策略服务/历史行情.md`:
     - 加 "Chunked Fetch" 段
     - 实测 30 天 → 3 段, 90 天 → 9 段

## 不做什么

- **不动 broker 端** (`iquant/quota_his.py`) — broker 单源真相
- **不动 EvTrade server 端** — 与本 change 无关
- **不动 MySQL schema** — 无 schema 改动
- **不动 strategy 算法** — run_backtest / sweep 逻辑不变
- **不动 aggregator** — chunks 拼完后再调 aggregator，逻辑不变
- **不动前端** — 无变化
- **不改并行** — 用户原话"全部取到了再后台拼凑到一起"，默认**串行**（避免并发压垮 broker），后续如需并行可加 `asyncio.gather`

## 影响面

| 模块 | 影响 |
|---|---|
| `strategy_exec/strategy_exec/config.py` | +2 字段 (his_hq_chunk_days / his_hq_chunk_enabled) |
| `strategy_exec/strategy_exec/market_data/hq_history.py` | +40 行 (chunked fetch + _iter_chunks) |
| `tests/strategy_exec/test_hq_history_chunked.py` | 新增 ~80 行 |
| `openspec/specs/strategy-exec/spec.md` | +30 行 (chunked 段) |
| `知识库/策略服务/历史行情.md` | +30 行 (Chunked Fetch 段) |

净变化: ~+180 行 (轻量)

## Commit 拆解 (v6)

```
1. feat(strategy-exec): config 加 chunk_days + hq_history 拆分调 broker
2. feat(strategy-exec): chunked fetch 合并 + debug log + 外部接口兼容
3. test(strategy-exec): chunked 单测 (7 cases)
4. test: 端到端验收 — 1 年 backtest chunked
5. docs: spec-delta merge + 归档 + 知识库同步
```

## 数据安全（用户硬规则 2026-08-27）

- [ ] 不动 MySQL schema
- [ ] 不 drop / truncate / delete from
- [ ] 不重建 schema
- [ ] 不动 strategy_task 数据
- [ ] chunked fetch 仅改 hq_history 内部实现，外部接口签名不变

## 验收 (v6 完成自查)

- [ ] pytest strategy_exec/strategy_exec/tests/test_hq_history_chunked.py → 0 fail (7 cases)
- [ ] pytest server/tests/ + tests/strategy_exec/ → 守住 139+ (新加 7 cases ≥ 146 passed)
- [ ] 端到端实测: 1 年 backtest 跑通, strategy_exec 日志显示 36 段 chunked (365/10)
- [ ] git diff --stat 每 commit 单目的
- [ ] 外部接口签名 `fetch_bars(stock, start, end, period, fields)` 不变
- [ ] aggregator + strategy_exec 集成测试通过 (chunked 拼完后再聚合)