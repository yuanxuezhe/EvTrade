# Tasks: quota-batch-fixture-sync (2026-08-27)

> 每个 task = 1 个 commit（v6 单 commit 单目的）。
> 本 change 只有 **1 个 commit**（纯测试代码）。

## Commit 拆解

- [ ] **commit 1**: `test(iquant): quota batch 删 4 个过时测试 + 改 TestConfig 对齐重构后设计 (P1-1 第 1 刀)`
  - 删 `TestBatchSizeThreshold::test_size_below_threshold_waits_timer`
  - 删 `TestBatchBytesThreshold::test_bytes_threshold_with_few_large_ticks`
  - 删 `TestBatchTimerThreshold` 整个类（2 个 test 都依赖 timer）
  - 改 `TestConfig::test_env_override` 移除 `QUOTA_FLUSH_MS` env 设置与断言
  - 新增 `test_enqueued_below_threshold_no_flush`（验证 size 阈值未达时不 flush）
  - 更新文件头 docstring（删除阈值 2/3 描述）

## 验证 (v6 完成自查)

- [ ] `pytest tests/test_quota_batch.py -v` → 6 passed / 0 failed
- [ ] `pytest hq/ server/tests/ tests/` → 134 collected / 127 passed / 7 failed（12 → 7）
- [ ] `git diff --stat` 显示改动**仅** `tests/test_quota_batch.py`

## 数据安全（用户硬规则 2026-08-27）

- [ ] 不动 MySQL 任何表/列/行
