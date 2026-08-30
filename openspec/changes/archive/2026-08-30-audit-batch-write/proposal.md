# Audit Batch Write — write_audit executemany 批量 INSERT (2026-08-30)

> 用户拍板 2026-08-30：修 audit 写入慢。`run_backtest` 12,040 signals × 单条 INSERT+commit 卡6分钟+, 长区间回测 `status='finished'` 状态延迟。

## Why

**实测 (2026-08-30)**:
- task26: 159992.SZ 20230101-20260828 period=1m
- 回测逻辑100% 跑通 (cache FULL HIT 174,240 bars + Backtrader 生成 12,040 BUY/SELL)
- RabbitMQ 12,040 信号全部推送成功
- **卡在 writing_result**: 12,040 次 write_audit 串行 INSERT+commit ≈ 6 分钟
- task27 (5 天1m, 63 trades): 11 秒跑完 (audit 写完正常 finished)

**根因**:
```python
# strategy_exec/data_access/strategy_task.py:226-276
for sig in collector.signals:   # 12,040 次循环
    write_audit(...)            # INSERT + session.commit() 同步阻塞
```
- 单进程 uvicorn event loop 串行 12,040 transactions
- 每条 INSERT ~30ms (跨进程 MySQL commit + JSON serialize)
- 总耗时: 12,040 × 30ms ≈ 6 分钟+

**用户硬规则**:
- 仅修 write_audit 性能 bug, 不改其他
- 不动 strategy_script_audit schema
- 不动 strategy_task 表数据
- 不影响其他模块 (live.py, sweep 等)

## What

### P0 — change 骨架

新建 `openspec/changes/2026-08-30-audit-batch-write/`, proposal + tasks + spec-deltas/strategy-exec.md。

### P1 — write_audit_batch + backtest 用 batch (2 commits)

1. **commit 1 — write_audit_batch helper**
   - `strategy_exec/data_access/strategy_task.py` 加 `write_audit_batch(rows: List[Dict]) -> int`
   - 单次 `executemany(INSERT)` + 一次 commit
   - 自动分批 (默认 1000/批, 防止超大事务)
   - 返写入条数 (含 batch 总和)
   - 保留 `write_audit` 单条版本 (live.py / sweep 仍可用)

2. **commit 2 — backtest.py 用 batch 替代逐条**
   - `strategy_exec/engines/backtrader/backtest.py:208-224` 改 `for sig: write_audit()` → 收集 List[Dict] → `write_audit_batch(rows)`
   - 性能: 12,040 INSERTs → 12 batch INSERTs → ~12 seconds (50x speedup)

### P2 — 单测 (1 commit)

3. **commit 3 — write_audit_batch 单测 (mock DB)**
   - `tests/strategy_exec/test_audit_batch_write.py`:
     - 单批 INSERT (rows < 1000) 一次性 executemany
     - 多批 INSERT (rows > 1000) 自动分批, commit 多次
     - 空 list 跳过 (返 0)
     - 字段序列化 (indicators / payload JSON 正确)
     - 错误 / DB 异常 → 返 0 (不影响回测主流程, 同原 write_audit 行为)
   - 验证基线: `pytest server/tests/ + tests/strategy_exec/` 守住

### P3 — 端到端 + 文档 (2 commits)

4. **commit 4 — 端到端 1 年回测验证**
   - 重跑 task25 (sid=12, 1 年1d, 已知 finished pnl=16.20)
   - 验证: write_audit_batch 调用, 100x+ speedup, status='finished' 快速写入
   - 留 trace 在 commit message

5. **commit 5 — spec-delta merge + 归档 + 知识库**
   - 改 `openspec/specs/strategy-exec/spec.md` 加 REQ-SE-015 audit batch
   - 归档 `mv openspec/changes/2026-08-30-audit-batch-write openspec/changes/archive/`
   - 改 `知识库/策略服务/架构概览.md` + `策略服务/历史行情.md` (审计写入说明)

## 不做什么

- **不动 strategy_script_audit schema**
- **不动 live.py** (其他场景暂不优化, followup 可做)
- **不动 sweep engine** (暂不优化)
- **不改单条 write_audit 签名** (保持向后兼容, batch 是新 helper)
- **不动前端** (无变化)

## 影响面

| 模块 | 影响 |
|---|---|
| `strategy_exec/strategy_exec/data_access/strategy_task.py` | +40 行 (write_audit_batch helper) |
| `strategy_exec/strategy_exec/engines/backtrader/backtest.py` | 改 16 行 (单条循环 → batch 调用) |
| `tests/strategy_exec/test_audit_batch_write.py` | 新增 ~80 行 |
| `openspec/specs/strategy-exec/spec.md` | +20 行 (REQ-SE-015) |
| `知识库/策略服务/架构概览.md` | +5 行 |
| `知识库/策略服务/历史行情.md` | +5 行 |

净变化: ~+150 行 (轻量)

## Commit 拆解 (v6)

```
1. feat(strategy-exec): write_audit_batch helper (executemany 自动分批 1000/批)
2. refactor(strategy-exec): backtest.py 用 batch 替代逐条 write_audit
3. test(strategy-exec): audit_batch_write 单测 (5 cases)
4. test: 端到端 — 1 年回测 batch 模式速度验证 (commit 留 trace)
5. docs: spec-delta merge + 归档 + 知识库同步
```

## 数据安全（用户硬规则 2026-08-27）

- [ ] 不动 MySQL schema (strategy_script_audit 不变)
- [ ] 不 drop / truncate / delete from
- [ ] 不重建 schema
- [ ] 不动 strategy_task 数据
- [ ] 不动其它表 (orders/trades/...)

## 验收 (v6 完成自查)

- [ ] pytest tests/strategy_exec/test_audit_batch_write.py → 0 fail (5 cases)
- [ ] pytest server/tests/ + tests/strategy_exec/ → 守住 188+ (新加 5 = 193)
- [ ] 端到端实测: 1 年回测 write_audit_batch 调用, finished 状态 5-10s 写入 (vs 原6 分钟)
- [ ] git diff --stat 每 commit 单目的
- [ ] 外部接口 write_audit 单条版本不变 (向后兼容)
- [ ] 字段序列化语义与原 write_audit 一致 (JSON 格式, NULL 处理)