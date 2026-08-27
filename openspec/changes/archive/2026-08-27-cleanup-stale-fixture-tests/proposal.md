# Cleanup: 删 2 个过时测试文件 + 改 1 个 fixture 不删表

> 用户拍板 2026-08-27：P1-1 第 3 刀 + 收尾。Why：pytest 12 fail 中的 5 fail 全部来自 fixture 删表 + 业务已废弃的过时测试。

## Why

`server/tests/` 下 12 个 fail 全部来自 3 个文件的 fixture 删表 + 业务代码已重构：

### 问题 1：fixture 删表（用户硬规则 2026-08-27 违规）

```
server/tests/test_orders_cancel.py:42-44
    s.execute(text("DELETE FROM trades"))
    s.execute(text("DELETE FROM orders"))
    s.execute(text("ALTER TABLE orders AUTO_INCREMENT = 1"))

server/tests/test_v78_skip_rebroadcast.py:34
    s.execute(text("DELETE FROM orders"))
```

跑这些测试会清空生产 orders 表。**P1-1 第 2 刀已发生事故**：生产 orders 那行被删。

### 问题 2：业务代码已重构，测试期望过时

| 测试文件 | 失败数 | 业务已重构 |
|---|---|---|
| `test_v78_skip_rebroadcast.py` | 4 | v78 时代 broker ord_cfm 1st/2nd ack 语义，**v118+ 持仓架构重做后已变** |
| `test_pos_push_diff.py` | 1 | v118 前 pos_push diff 逻辑（broker 推送无变化时 server 端跳过落库），**v118 后改为 broker 权威直接覆盖本地**（`server/services/push/pos.py:90-101`） |

### 测试文件价值评估

| 文件 | 行数 | 业务覆盖价值 | fixture 删表 | 决定 |
|---|---|---|---|---|
| `test_orders_cancel.py` | 325 | **高**（撤单核心路径 6 场景） | ❌ 是 | **保留 + 改 fixture** |
| `test_v78_skip_rebroadcast.py` | 230 | **零**（v78 已废 2 年，v118+ 架构重做后无意义） | ❌ 是 | **删除** |
| `test_pos_push_diff.py` | 285 | **零**（diff 语义已取消） | ✅ 否（用 monkeypatch） | **删除**（业务已被新架构覆盖） |

## What

**3 commit**（按 v6 规范）：
1. **commit 1**: `test(orders): cancel 改 fixture 不删表 + 用 mock_trd_date 隔离 (P1-1 第 3 刀 a)`
2. **commit 2**: `chore(test): 删 test_v78_skip_rebroadcast.py (v78 旧回归 + 4 fail + fixture 删表)`
3. **commit 3**: `chore(test): 删 test_pos_push_diff.py (v118 前 diff 语义已废 + 1 fail)`

### 改动 1：test_orders_cancel.py fixture 不删表

```python
# 改前: DELETE FROM trades / orders / ALTER AUTO_INCREMENT=1
@pytest.fixture
def db():
    s = SessionLocal()
    s.execute(text("DELETE FROM trades"))
    s.execute(text("DELETE FROM orders"))
    s.execute(text("ALTER TABLE orders AUTO_INCREMENT = 1"))
    ...

# 改后: 不删表, 仅清测试用户 (admin/trader 排除)
@pytest.fixture
def db():
    s = SessionLocal()
    yield s
    s.execute(text("DELETE FROM users WHERE LOCATE('_', username) > 0 AND username NOT IN ('admin', 'trader')"))

# 新增 mock_trd_date fixture (同 test_place_async.py 模式)
@pytest.fixture
def mock_trd_date(monkeypatch):
    """Mock _get_active_trd_date → '99990718' 隔离测试数据与生产数据"""
    ...

# 改 trd_date 硬编码 "20260825" → mock_trd_date (5 处)
```

### 改动 2：删除 test_v78_skip_rebroadcast.py

**原因**：
- 4 个 fail（test_first_ack_writes_50_and_broadcasts 等）100% 来自 v78 时代语义
- v118+ 持仓架构重做后，handle_ord_cfm 流程已变
- fixture 还删 orders 表
- 业务已被 `test_place_async.py` 7 个 test 覆盖（更现代）

### 改动 3：删除 test_pos_push_diff.py

**原因**：
- 1 个 fail（test_no_change_returns_none_and_skips_update）来自已删除的 diff 语义
- `server/services/push/pos.py:90-101` 当前实现是 broker 权威直接覆盖，**没有 diff**
- 业务覆盖价值为零（测试假设的语义不存在）
- 无 fixture 删表问题（用 monkeypatch），但保留也无意义

## 不做什么

- **不动** `test_orders_cancel.py` 的 6 个测试用例（happy / pre-check / RPC 异常）—— 仅改 fixture
- **不动** 任何生产代码
- **不动** DB 任何数据（用户硬规则）
- **不动** `test_quota_batch.py` / `test_place_async.py`（P1-1 第 1/2 刀已 done）

## 验证 (v6 完成自查)

- [ ] `pytest server/tests/test_orders_cancel.py -v` → 6 passed / 0 failed（fixture 改后）
- [ ] `pytest server/tests/ --tb=no -q` → 0 failed（删 2 文件 + 改 1 fixture 后）
- [ ] **生产 orders 表未变**：`SELECT COUNT(*) FROM orders` 仍 = 0（事故后已无数据，但后续测试不能清）
- [ ] `grep -rE "DELETE FROM orders|TRUNCATE|ALTER TABLE" server/tests/` → 0 命中
- [ ] `git diff --stat` 仅含 `test_orders_cancel.py` 改动（删 2 个文件单 commit）
- [ ] commit message: `test(orders): cancel 改 fixture 不删表 + 用 mock_trd_date` / `chore(test): 删 test_v78_skip_rebroadcast.py` / `chore(test): 删 test_pos_push_diff.py`
- [ ] 归档：`mv openspec/changes/2026-08-27-cleanup-stale-fixture-tests openspec/changes/archive/`

## 数据安全（用户硬规则 2026-08-27）

- 不动 MySQL 任何表/列/行
- 删 2 文件不涉及代码逻辑修改（仅删过时测试代码）
- 改 1 fixture 不删 orders/trades 表

## 关联

- P1-1 第 1 刀: `test_quota_batch.py` 5→0 fail (commit `9478140`)
- P1-1 第 2 刀: `test_place_async.py` 6→0 fail (commit `59ec5ae`)
- **本 change**: 删 2 文件 + 改 1 fixture = 5→0 fail (清理 test_orders_cancel 残留 fixture 风险)
