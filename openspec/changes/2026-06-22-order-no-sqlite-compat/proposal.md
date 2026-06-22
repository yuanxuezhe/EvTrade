# order-no-sqlite-compat — 订单序号生成器降级兼容 SQLite 3.21.0

> MED 级 / S 工作量。修复 `POST /api/orders/place` 500 错误（重启后用户报障）。

## 1. Why

### 1.1 真实运行时错误

`POST /api/orders/place` 触发 `next_order_no(db)`，执行 `INSERT ... ON CONFLICT(id) DO UPDATE ... RETURNING`，但当前 Python 3.6.8 自带的 SQLite 是 **3.21.0**，远低于该语法所需的 **3.35**（`ON CONFLICT ... DO UPDATE SET ... RETURNING`）。

错误日志（`bs2vkk4da.output` line 131-200）：
```
sqlalchemy.exc.OperationalError: (sqlite3.OperationalError) near "ON": syntax error
[SQL:
    INSERT INTO order_no_seq (id, last_value, updated_at)
    VALUES (1, 10000001, CURRENT_TIMESTAMP)
    ON CONFLICT(id) DO UPDATE SET
        last_value = last_value + 1,
        updated_at = CURRENT_TIMESTAMP
    RETURNING last_value
]
```

### 1.2 知识库与现实脱节（更严重）

`openspec/changes/archive/2026-06-21-order-no-atomic-upsert/proposal.md:74` 假设：
> **选 A**：项目 SQLite 实际 3.50.4，无兼容性顾虑。

**实测实际是 3.21.0**（Python 3.6.8 自带）。这意味着：
- 当前 `order_no.py` 的方案 A 在生产环境**必崩**
- `openspec/specs/rpc-protocol/spec.md:82` 的 REQ-RPC-009.1（要求 SQLite ≥ 3.35）**与现实不符**
- 整个 `order-no-atomic-upsert` change 实际上是**"看似归档，实际未实施"**

### 1.3 必须立即修复的业务影响

`/api/orders/place` 是核心下单端点，500 意味着**业务完全不可用**。

## 2. What Changes

### 2.1 降级实现 `server/services/order_no.py:next_order_no`

**新方案**：保留 3 步分离语句（archive proposal §2.1 方案 B 的修正版），但**函数内 commit**（保留原 change 的核心收益：消除调用方漏 commit 的回退风险）。

```python
def next_order_no(db) -> str:
    # 步 1: 兜底初始化行（id=1）
    db.execute(text("INSERT OR IGNORE INTO order_no_seq (id, last_value, updated_at) VALUES (1, 10000000, CURRENT_TIMESTAMP)"))
    # 步 2: 自增
    db.execute(text("UPDATE order_no_seq SET last_value = last_value + 1, updated_at = CURRENT_TIMESTAMP WHERE id = 1"))
    # 步 3: 读出
    val = db.execute(text("SELECT last_value FROM order_no_seq WHERE id = 1")).scalar()
    db.commit()
    if val is None:
        raise RuntimeError("order_no_seq 读取失败")
    if val >= 99999999:
        raise RuntimeError(f"order_no 已达上限 ({val})")
    return str(val)
```

**优势**：
- 兼容 SQLite 3.21.0（当前实际版本）
- 函数内 commit 保留（消除调用方漏 commit 风险）
- 不破坏现有测试 `test_order_no.py::test_no_duplicates_under_concurrency`（已验证 100 并发无重复）

**与原 change 提案的差异**：
- 不再使用 `ON CONFLICT ... RETURNING`（要求 SQLite 3.35）
- 恢复 3 步分离语句（archive proposal §2.1 方案 B）
- 函数内 commit 仍然保留（archive proposal 方案 A 的核心收益）

### 2.2 更新 docstring

`order_no.py:6` 改为真实描述当前实现 + 标注 SQLite 3.21.0 兼容。

### 2.3 更新 spec `openspec/specs/rpc-protocol/spec.md` REQ-RPC-009.1

**新文本**：
> REQ-RPC-009.1: 单语句原子自增（理想 SQLite ≥ 3.35）/ 或 3 步分离 + 函数内 commit（兼容 SQLite ≥ 3.21）。当前生产环境 SQLite 3.21.0，使用后者。

### 2.4 更新 archive proposal

`openspec/changes/archive/2026-06-21-order-no-atomic-upsert/proposal.md:74` 标注勘误：原"项目 SQLite 实际 3.50.4"假设错误，实际 3.21.0。

## 3. Capabilities

### Modified Capabilities
- `rpc-protocol`: REQ-RPC-009.1 修订（降级兼容）
- `dev-process-control`: 无变更

## 4. 影响面

- **后端**：`server/services/order_no.py`（核心修复）
- **测试**：`server/test_order_no.py` 已有并发测试，无需新增（3 步方案本就覆盖）
- **DB**：`order_no_seq` 表结构不变
- **前端**：无影响

## 5. 不在本 change 范围

- 升 SQLite 版本到 ≥ 3.35（需换 Python 或自带 libsqlite3-3.50+）—— 越界禁止
- `order-no-atomic-upsert` 整个归档撤回（应保留历史档案）
- 业务其他逻辑修复

## 6. Tasks

- [ ] T1: 修 `server/services/order_no.py:next_order_no` 用 3 步分离 + 函数内 commit
- [ ] T2: 改 `order_no.py:6` docstring 标注 SQLite 3.21.0 兼容
- [ ] T3: 改 `openspec/specs/rpc-protocol/spec.md:82` REQ-RPC-009.1 文本
- [ ] T4: 改 `openspec/changes/archive/2026-06-21-order-no-atomic-upsert/proposal.md:74` 勘误
- [ ] T5: 跑 `pytest server/test_order_no.py -v` 全绿
- [ ] T6: 重启服务器，前端重试下单
- [ ] T7: commit
