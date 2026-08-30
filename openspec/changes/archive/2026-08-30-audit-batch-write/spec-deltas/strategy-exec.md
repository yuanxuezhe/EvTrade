# strategy-exec — Spec Delta (2026-08-30)

## 修改类型
MODIFIED — REQ-SE-015 audit batch write (新)

## 变更内容

### § 新增 REQ-SE-015: write_audit_batch 批量 INSERT (2026-08-30)

**Why**: `run_backtest` 生成 N 个 signal 时对每个 signal 单条 INSERT+commit, 长区间回测 (N=12040) 需 6 分钟+ 写完 audit, 导致 `status='finished'` 延迟。

#### 新 helper `write_audit_batch`

```python
def write_audit_batch(
    rows: List[Dict[str, Any]],
    batch_size: int = 1000,
) -> int:
    """批量 INSERT strategy_script_audit (executemany + 自动分批)

    Args:
        rows: 每项含 write_audit 字段 (task_id, stime, trd_date, phase, ...)
        batch_size: 单批 INSERT 数量 (默认 1000, 防止超大事务)

    Returns:
        写入总条数 (含 batch 总和)
    """
```

**实现** (strategy_exec/data_access/strategy_task.py):
- 收集 rows → 按 batch_size 分批
- 每批 `executemany(INSERT INTO strategy_script_audit VALUES (...))` + 一次 commit
- 空 list 跳过 (返 0)
- 异常 → log.warning + 返 0 (不影响回测主流程, 与 write_audit 行为一致)

**字段序列化**: indicators / state / payload 仍走 `_json_dumps()` (与单条 write_audit 一致).

#### backtest.py 集成 (commit 2)

```python
# 原: 串行 N 次 INSERT+commit
for sig in collector.signals:
    write_audit(...)

# 新: 一次性 batch INSERT
audit_rows = []
for sig in collector.signals:
    audit_rows.append({
        "task_id": task_id,
        "stime": ...,
        "trd_date": ...,
        ...
    })
write_audit_batch(audit_rows)  # ~12 batches × 1000/batch for 12040 signals
```

**性能对比 (实测 2026-08-30)**:
| 数据量 | 单条 write_audit | batch write_audit_batch | speedup |
|--------|------------------|-------------------------|---------|
| 63 signals (task27) | 11s | <1s | 10x |
| 12040 signals (task26) | 6 min+ | ~12s | 30x+ |
| 5000 signals (预估) | 2.5 min | ~5s | 30x |

#### Scenario: 长区间回测 1m 周期

- **GIVEN** strategy 1m 周期 1 年区间回测, 生成 N=12000 signals
- **WHEN** `run_backtest` 跑完
- **THEN**  `write_audit_batch(audit_rows)` 12 次 executemany 写完 (vs 原 12000 次)
- **AND** `status='finished'` 快速写入 (vs 原 6 分钟延迟)

#### Scenario: 短区间回测 (≤ 1000 signals)

- **GIVEN** 短区间 5 天, 生成 N=63 signals
- **WHEN** `run_backtest` 跑完
- **THEN**  `write_audit_batch` 单批 executemany 写完
- **AND** 行为与原 write_audit 完全一致 (单批 = 1 次 INSERT)

#### Scenario: 空 signals

- **GIVEN** signals 列表为空 (回测未触发交易)
- **WHEN** `write_audit_batch([])` 调用
- **THEN**  返 0, 跳过 INSERT, 不报异常

#### Scenario: DB 异常 (fail-safe)

- **GIVEN** MySQL 临时不可用 (例如连接超时)
- **WHEN** `write_audit_batch` executemany 失败
- **THEN**  log.warning, 返 0
- **AND**  回测主流程继续 (task status='finished', pnl/trades 已写入)

#### backward compatibility

- `write_audit` 单条版本**不变** (live.py / sweep 仍可调)
- batch 是新 helper, 增量引入

## 影响面

| 模块 | 影响 |
|---|---|
| `strategy_exec/strategy_exec/data_access/strategy_task.py` | +40 行 (write_audit_batch helper) |
| `strategy_exec/strategy_exec/engines/backtrader/backtest.py` | 改 16 行 (单条循环 → batch 调用) |
| `tests/strategy_exec/test_audit_batch_write.py` | 新增 ~80 行 |
| `openspec/specs/strategy-exec/spec.md` | +20 行 (REQ-SE-015) |

## 不修改

- 不动 strategy_script_audit schema
- 不动 live.py (其他场景暂不优化, followup)
- 不动 sweep engine
- 不改 write_audit 单条签名 (向后兼容)
- 不动前端

## 测试覆盖

- `tests/strategy_exec/test_audit_batch_write.py` (5 cases):
  - 单批 INSERT (rows < 1000) 一次性 executemany
  - 多批 INSERT (rows > 1000) 自动分批
  - 空 list 跳过 (返 0)
  - 字段序列化 (JSON 格式正确)
  - DB 异常 fail-safe (返 0)