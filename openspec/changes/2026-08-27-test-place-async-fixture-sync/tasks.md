# Tasks: test-place-async-fixture-sync (2026-08-27)

> 每个 task = 1 个 commit（v6 单 commit 单目的）。
> 本 change 只有 **1 个 commit**（纯测试代码）。

## Commit 拆解

- [ ] **commit 1**: `test(orders): place_async 改 fixture 不删表 + 6 个 test 对齐 v11 后设计 (P1-1 第 2 刀)`
  - 改 `db()` fixture：去掉 `DELETE FROM orders` + `ALTER TABLE AUTO_INCREMENT = 1`
  - 改 `trader()` fixture：去掉 `SysStatus.delete_one/upsert_one`
  - 新增 `mock_trd_date()` fixture：`monkeypatch _get_active_trd_date → '99990718'`
  - 改 `_make_order`：默认 trd_date=`'99990718'`，user_def 加 `_test_` 前缀
  - 改 6 个 test 期望（对齐 v11 broker 字典对齐后代码行为）

## 验证 (v6 完成自查)

- [ ] `pytest server/tests/test_place_async.py -v` → 5+ passed / 0 failed
- [ ] `pytest hq/ server/tests/ tests/` → collected / passed / failed 数字按实记录
- [ ] **生产数据未变**：`SELECT COUNT(*) FROM orders` 仍 = 1
- [ ] `git diff --stat` 显示改动**仅** `server/tests/test_place_async.py`

## 数据安全（用户硬规则 2026-08-27）

- [ ] 不动 MySQL 任何表/列/行
- [ ] fixture 不写 DELETE FROM / TRUNCATE / ALTER TABLE
