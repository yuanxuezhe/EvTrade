# Fix: test_quota_batch 5 个 fail — 对齐 iquant/quota.py 重构后设计

> 用户拍板 2026-08-27：P1-1 pytest 12 failing 第一刀。Why 详见 `CLAUDE.md` § 八"历史失败归属"表。

## Why

`tests/test_quota_batch.py` 5 个 fail 全部是 **测试期望 vs `iquant/quota.py` 重构后实际设计** 不一致：

| Fail | 测试期望 | 代码实际 | 根因 |
|---|---|---|---|
| `TestBatchSizeThreshold::test_size_below_threshold_waits_timer` | 49 条 < 50 条，等 **200ms timer** flush | `iquant/quota.py:66` 只在 `len(self._buf) >= QUOTA_BATCH_MAX (50)` 时 flush，**无 timer 线程** | v131 重构删除 timer 阈值，测试未同步 |
| `TestBatchBytesThreshold::test_bytes_threshold_with_few_large_ticks` | 22 条大 tick 累计 > 8KB 立即 flush | `_flush_locked` **无字节数阈值**检查 | v131 重构删除 bytes 阈值，测试未同步 |
| `TestBatchTimerThreshold::test_timer_flush_slow_market` | 1 条后 200ms 内 timer flush | 无 timer | 同上 |
| `TestBatchTimerThreshold::test_timer_quiet_then_burst` | 同上 | 无 timer | 同上 |
| `TestConfig::test_env_override` | `QUOTA_FLUSH_MS` env 覆盖后 `config.QUOTA_FLUSH_MS == 100` | `Config` 类**无 `QUOTA_FLUSH_MS` 属性** | timer 阈值删除后属性也删除 |

### 关键代码证据

`iquant/quota.py:58-67` (GBK 编码注释解码后):

```python
def enqueue(self, line: bytes):
    """on_quote 回调线程: 入队 (size-only 阈值: tick 数 >= 50 才 flush)"""
    with self._lock:
        self._buf.append(line)
        self._byte_len += len(line) + 1

        # 唯一阈值: tick 数 >= 50 才 flush
        # (bytes / timer 阈值已删, on_quote 满 50 才分片, 中间不 buffer)
        if len(self._buf) >= config.QUOTA_BATCH_MAX:
            self._flush_locked()
```

### timer 阈值现在在哪？

后端 `server/services/strategy/quote_consumer.py`（v131 重构后）才是负责 batch flush 的层 —— 它有 **50 tick OR 1s timer** 双触发（详见 `v120-evtrade-services-topology` skill §10 Quote-batch-flush 架构）。`iquant/quota.py` 是更上游的 UDP 转发层，按 size 分片即可，不再维护 timer 线程。

## What

**单 commit 单目的**（按 v6 规范）：纯测试代码改动，零生产代码改动，零数据风险。

1. **删 4 个已不适用测试**：
   - `TestBatchSizeThreshold::test_size_below_threshold_waits_timer`（依赖 timer）
   - `TestBatchBytesThreshold::test_bytes_threshold_with_few_large_ticks`（依赖 bytes 阈值）
   - `TestBatchTimerThreshold::test_timer_flush_slow_market`（依赖 timer）
   - `TestBatchTimerThreshold::test_timer_quiet_then_burst`（依赖 timer）

2. **改 TestConfig**：移除 `QUOTA_FLUSH_MS` env 设置与断言（属性已删除）

3. **保留 5 个仍然适用的测试**：
   - `test_size_threshold_50`（核心 size 阈值）
   - `TestWireFormatCompat::*` 3 个（协议格式）
   - `TestConcurrency::test_concurrent_enqueue_no_loss`（并发）

4. **新增 1 个测试** `test_enqueued_below_threshold_no_flush` 覆盖"未达 50 不 flush"（当前无此测试覆盖）

5. **更新文件头 docstring**：删除"阈值 2 / 阈值 3"描述，只保留 size 阈值

## 不做什么

- **不动** `iquant/quota.py`（重构后设计合理，timer 在后端层）
- **不动** `server/services/strategy/quote_consumer.py`（已有 timer 实现）
- **不动** DB（用户硬规则 2026-08-27）
- **不动** `server/tests/` 任何文件（本 change 只动 `tests/test_quota_batch.py`）

## 验证 (v6 完成自查)

- [ ] `pytest tests/test_quota_batch.py -v` → 6 passed / 0 failed（5 → 6 个 case）
- [ ] `pytest hq/ server/tests/ tests/` → 134 collected / 127 passed / 7 failed（基线从 12 fail 降到 7 fail）
- [ ] `git diff --stat` 显示改动**仅** `tests/test_quota_batch.py`
- [ ] commit message: `test(iquant): quota batch 删 4 个过时测试 + 改 TestConfig 对齐重构后设计 (P1-1 第 1 刀)`
- [ ] 归档：`mv openspec/changes/2026-08-27-quota-batch-fixture-sync openspec/changes/archive/`

## 数据安全（用户硬规则 2026-08-27）

- 不动 MySQL 任何表/列/行
- 不 drop / truncate / delete from
- 不重建 schema

## 关联

- 上一轮 P0-1：CLAUDE.md § 八记录 12 fail 归属，本 change 关闭 5 个（quota_batch）
- 后续 P1-1 剩余：test_place_async 6 fail + test_pos_push_diff 1 fail + test_v78_skip_rebroadcast 1 fail
