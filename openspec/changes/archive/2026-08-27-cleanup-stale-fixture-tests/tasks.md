# Tasks: cleanup-stale-fixture-tests (2026-08-27)

> 每个 task = 1 个 commit（v6 单 commit 单目的）。本 change 有 **3 commit**。

## Commit 拆解

- [ ] **commit 1**: `test(orders): cancel 改 fixture 不删表 + 用 mock_trd_date 隔离 (P1-1 第 3 刀 a)`
  - `server/tests/test_orders_cancel.py`: 删 `DELETE FROM trades/orders` + `ALTER TABLE AUTO_INCREMENT = 1`
  - 新增 `mock_trd_date()` fixture
  - 改 5 处 `trd_date="20260825"` → `trd_date=mock_trd_date` (从 fixture 拿隔离日期)

- [ ] **commit 2**: `chore(test): 删 test_v78_skip_rebroadcast.py (v78 旧回归 + 4 fail + fixture 删表)`
  - `git rm server/tests/test_v78_skip_rebroadcast.py` (230 行)

- [ ] **commit 3**: `chore(test): 删 test_pos_push_diff.py (v118 前 diff 语义已废 + 1 fail)`
  - `git rm server/tests/push/test_pos_push_diff.py` (285 行)

## 验证 (v6 完成自查)

- [ ] `pytest server/tests/test_orders_cancel.py -v` → 6+ passed / 0 failed
- [ ] `pytest server/tests/ --tb=no -q` → 0 failed
- [ ] `grep -rE "DELETE FROM orders|TRUNCATE|ALTER TABLE" server/tests/` → 0 命中
- [ ] `git diff --stat` 仅含本 change 涉及文件

## 数据安全（用户硬规则 2026-08-27）

- [ ] 不动 MySQL 任何表/列/行
- [ ] fixture 改后不再 DELETE/TRUNCATE/ALTER TABLE
