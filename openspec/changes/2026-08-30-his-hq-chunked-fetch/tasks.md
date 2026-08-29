# Tasks: his-hq-chunked-fetch (2026-08-30)

> 每个 task = 1 个 commit（v6 单 commit 单目的）。
> 整体按 P0→P1→P2→P3 顺序推进。

## P0 — change 骨架

- [ ] **commit 0 (骨架)** — 已通过 proposal/tasks/spec-delta 文件创建完成

## P1 — strategy_exec 端实现

- [ ] **commit 1 — config + hq_history chunked fetch 拆分**
  - `strategy_exec/strategy_exec/config.py`:
    - `his_hq_chunk_days: int = Field(default=10, ge=1, le=30)`
    - `his_hq_chunk_enabled: bool = Field(default=True)`
  - `strategy_exec/strategy_exec/market_data/hq_history.py`:
    - 新增 `_iter_chunks(start, end, chunk_days) -> List[Tuple[str, str]]` 纯函数
    - 改 `fetch_bars()` 入口:
      - 若 `his_hq_chunk_enabled` 关闭 → 保留原 1 次拉全区间 (向后兼容)
      - 若开启 → 拆 N 段串行调 `_fetch_one_chunk(start, end, period)`
      - 每段独立 30s 超时
      - N 段全部成功 → 拼凑 + sort by stime
      - 任一段 raise → 立即 raise (不返部分数据)
    - 抽 `_fetch_one_chunk(start, end, period)` 私有方法: broker 调用 + 1m 聚合
  - 验收: `uv run python -c "from strategy_exec.market_data.hq_history import fetch_his_bars; ..."` import 不报错

- [ ] **commit 2 — 拼凑 + debug log + 外部接口兼容**
  - 拼凑时按 stime 升序 (broker stub 可能乱序)
  - 1d 聚合仍走 `aggregator.aggregate_bars()` (在 chunks 拼完之后)
  - 外部接口签名 `fetch_bars(stock, start, end, period, fields)` 不变
  - 加 debug log: `[hq_history] chunked fetch: 3 chunks (20250101-20250110, 20250111-20250120, 20250121-20250130)`
  - 验收: 实测 90 天 fetch 走 9 段, 日志显示 chunked 路径

## P2 — 单测

- [ ] **commit 3 — chunked 单测**
  - 新 `tests/strategy_exec/test_hq_history_chunked.py`:
    - `_iter_chunks` 纯函数 (5 cases):
      - 30 天 / chunk=10 → 3 段
      - 31 天 / chunk=10 → 4 段
      - start == end → 1 段
      - 跨年 (20241201-20250131) / chunk=30 → 2 段
      - chunk_days=1 → 每天 1 段 (退化)
    - chunked fetch 集成 (2 cases):
      - mock 2 段 fetch → 拼成完整 bars (按 stime 排序)
      - mock 1 段失败 → raise HQHistoryError (不返部分数据)
  - 验收: 7 cases 全过
  - 跑全基线: `pytest server/tests/ tests/strategy_exec/ -q` 守住 139+ (新加 7 = 146)

## P3 — 端到端 + 文档

- [ ] **commit 4 — 端到端验收 (1 年 backtest)**
  - 提交 sid=12 single backtest 20250101-20251231 period=1d
  - 验证:
    - strategy_exec 日志显示 36 段 chunked fetch (365/10 ≈ 37, 边界调整)
    - broker 单段 fetch 都成功
    - 全部 chunk 拼成 1d K 线 (200+ 根)
    - run_backtest status=finished (broker stub close=0 仍可能 failed, 但 chunked 路径打通)
  - 留 trace 在 commit message

- [ ] **commit 5 — spec-delta merge + 归档 + 知识库**
  - 改 `openspec/specs/strategy-exec/spec.md` REQ-SE-012-broker-1m-aggregate 段:
    - 加 Chunked Fetch 段
    - 加 config `his_hq_chunk_days=10` / `his_hq_chunk_enabled=True`
  - 归档: `mv openspec/changes/2026-08-30-his-hq-chunked-fetch openspec/changes/archive/`
  - 改 `知识库/策略服务/历史行情.md`:
    - 加 Chunked Fetch 段
    - 实测 30 天 → 3 段, 90 天 → 9 段, 1 年 → 36 段

## 验证 (v6 完成自查)

- [ ] pytest tests/strategy_exec/test_hq_history_chunked.py → 0 fail (7 cases)
- [ ] pytest server/tests/ + tests/strategy_exec/ → 守住 (146+ passed)
- [ ] 端到端实测: 1 年 backtest chunked 路径打通
- [ ] git diff --stat 每 commit 单目的
- [ ] 外部接口签名 `fetch_bars(stock, start, end, period, fields)` 不变
- [ ] aggregator 集成正常 (chunked 拼完后调 aggregator)