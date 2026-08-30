# Tasks: audit-batch-write (2026-08-30)

> 每个 task = 1 个 commit（v6 单 commit 单目的）。
> 整体按 P0→P1→P2→P3 顺序推进。

## P0 — change 骨架

- [ ] **commit 0 (骨架)** — proposal + tasks + spec-deltas 已创建

## P1 — write_audit_batch helper + backtest 用 batch

- [ ] **commit 1 — write_audit_batch helper**
  - `strategy_exec/strategy_exec/data_access/strategy_task.py` 加 `write_audit_batch(rows: List[Dict]) -> int`
  - 单次 `executemany(INSERT)` + 一次 commit
  - 自动分批 (默认 1000/批, 防止超大事务)
  - 返写入条数
  - 保留 `write_audit` 单条版本 (live.py / sweep 仍可用)

- [ ] **commit 2 — backtest.py 用 batch 替代逐条**
  - `strategy_exec/strategy_exec/engines/backtrader/backtest.py:208-224` 改 `for sig: write_audit()` → 收集 List[Dict] → `write_audit_batch(rows)`
  - 性能: 12,040 INSERTs → 12 batch INSERTs → ~12 seconds (50x speedup)

## P2 — 单测

- [ ] **commit 3 — write_audit_batch 单测 (5 cases)**
  - `tests/strategy_exec/test_audit_batch_write.py`:
    - 单批 INSERT (rows < 1000) 一次性 executemany
    - 多批 INSERT (rows > 1000) 自动分批, commit 多次
    - 空 list 跳过 (返 0)
    - 字段序列化 (indicators / payload JSON 正确)
    - 错误 / DB 异常 → 返 0 (不影响回测主流程)
  - 验收: 5 cases 全过

## P3 — 端到端 + 文档

- [ ] **commit 4 — 端到端 1 年回测验证**
  - 重跑 task25 (sid=12, 1 年1d, 已知 finished pnl=16.20)
  - 验证: write_audit_batch 调用, 100x+ speedup, status='finished' 快速写入
  - 留 trace 在 commit message

- [ ] **commit 5 — spec-delta merge + 归档 + 知识库**
  - 改 `openspec/specs/strategy-exec/spec.md` 加 REQ-SE-015 audit batch
  - 归档 `mv openspec/changes/2026-08-30-audit-batch-write openspec/changes/archive/`
  - 改 `知识库/策略服务/架构概览.md` + `策略服务/历史行情.md` (审计写入说明)

## 验证 (v6 完成自查)

- [ ] pytest tests/strategy_exec/test_audit_batch_write.py → 0 fail (5 cases)
- [ ] pytest server/tests/ + tests/strategy_exec/ → 守住 188+ (新加 5 = 193)
- [ ] 端到端实测: 1 年回测 batch 模式 speedup 显著
- [ ] git diff --stat 每 commit 单目的
- [ ] 外部接口 write_audit 单条版本不变 (向后兼容)
- [ ] 字段序列化语义与原 write_audit 一致