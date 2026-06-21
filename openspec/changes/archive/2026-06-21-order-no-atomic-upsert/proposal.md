# order-no-atomic-upsert — 订单序号生成器改为单语句原子 UPSERT

> MED 级 / M 工作量。消除"调用方漏 commit 导致序号回退"和"docstring 与实现不符"2 个真实问题。

## 1. Why

`server/services/order_no.py:next_order_no` 当前实现存在 **2 个真实问题**：

### 问题 A：docstring 与实现不符（注释撒谎）

`order_no.py:6` docstring 写"原子自增（SQLite UPSERT + RETURNING）"，但 line 28-37 实际是**3 步分离语句**：
```python
db.execute(text("INSERT OR IGNORE INTO order_no_seq ..."))   # step 1
db.execute(text("UPDATE order_no_seq SET last_value = ...")) # step 2
db.execute(text("SELECT last_value FROM order_no_seq ..."))   # step 3
```
注释承诺的特性（"原子 UPSERT + RETURNING"）**实现里完全没用**。

### 问题 B：调用方漏 commit 导致序号回退（真 bug）

`order_no.py:10` 注释说"调用方负责 commit"。`test_order_no.py:60` 测试断言 `10000000 < int(n) < 10000000 + 200`，但**未模拟"调用方异常未 commit"场景**。

**真实风险路径**：
```
place_order() 调用 next_order_no(db) → 返回 "10000001"
    ↓
orders INSERT (含 order_no=10000001) → 失败 (例如 stock_code 校验失败)
    ↓
db.rollback() 撤销 orders INSERT
    ↓
但 last_value 已经在 step 2 +1，下次 next_order_no 仍从 10000001 开始
    ↓
下次 place_order 拿到 "10000001" → UNIQUE 冲突 (如果上次 order 已 commit)
    ↓
或者如果上次没 commit → 拿到同样序号 = 重复
```

注意：audit 草稿 §2.3 说"竞态风险"实际是**误判**（SQLite 串行化已保证原子性，且 test_no_duplicates_under_concurrency 已验证 100 并发无重复）。**真问题是"回退风险"**。

## 2. What Changes

### 2.1 改 `server/services/order_no.py:next_order_no`

**方案 A（推荐）**：SQLite ≥ 3.35 单语句 `INSERT ... ON CONFLICT DO UPDATE ... RETURNING`
```python
def next_order_no(db) -> str:
    row = db.execute(text("""
        INSERT INTO order_no_seq (id, last_value, updated_at)
        VALUES (1, 10000001, CURRENT_TIMESTAMP)
        ON CONFLICT(id) DO UPDATE SET
            last_value = last_value + 1,
            updated_at = CURRENT_TIMESTAMP
        RETURNING last_value
    """)).first()
    if not row:
        raise RuntimeError("order_no_seq UPSERT 失败")
    val = row[0]
    if val >= 99999999:
        raise RuntimeError(f"order_no 已达上限 ({val})")
    db.commit()  # 改为函数内 commit, 消除"调用方漏 commit"风险
    return str(val)
```

**优势**：
1. **单语句** UPSERT，SQLite 串行化保证原子（不依赖应用层锁）
2. **函数内 commit**（破坏"调用方负责 commit"旧约定）—— 这是**有意打破**，消除回退风险
3. **docstring 与实现一致**

**方案 B（备选）**：保留 3 步但改 commit 时机
- 改函数内 commit，但保留 3 步语句
- 优点：兼容老 SQLite（< 3.24）
- 缺点：仍 3 步 IO，性能差；不能解决 docstring 撒谎

**选 A**：项目 SQLite 实际 3.50.4，无兼容性顾虑。

### 2.2 改 docstring

`order_no.py:6` 改为真实描述：
```python
- 单语句原子 UPSERT（SQLite ≥ 3.35 的 INSERT ... ON CONFLICT DO UPDATE ... RETURNING）
- 函数内自动 commit（调用方无需 commit，破坏旧约定）
```

### 2.3 调用方适配

`server/api/orders.py:place_order` 调用 `next_order_no(db)` 后**不需 commit**（函数内已 commit）。
但调用方可能仍想 `db.commit()` 提交 Order INSERT —— **仍要 commit**，但**不应**因为 `next_order_no` 失败而回滚 last_value。

实际逻辑：
```python
# place_order 简化流程
order_no = next_order_no(db)  # 内部已 commit
db.add(Order(order_no=order_no, ...))
db.commit()  # commit Order; 若失败 last_value 已 +1 但 Order 未入库,序号跳号
```

**序号跳号是 acceptable**（实际生产中下单序号本来就跳，柜台拒单/重复下单都会跳号）。

### 2.4 新增测试 `test_order_no_atomic.py`

```python
def test_atomic_no_callback_commit():
    """模拟调用方拿到 order_no 后异常 rollback, 验证下次 next_order_no 返回新值"""
    db = SessionLocal()
    n1 = next_order_no(db)
    db.rollback()  # 调用方回滚, 模拟失败
    n2 = next_order_no(db)
    db.close()
    assert n1 != n2  # 序号已 +1, 即使回滚也不回退

def test_upsert_single_statement():
    """验证实现用单语句 UPSERT, 不依赖应用层锁"""
    # 100 协程并发, 应 100 个唯一值
```

## 3. Capabilities

### Modified Capabilities
- `rpc-protocol`: 新增 REQ-RPC-009 订单序号生成约定（见 spec-deltas/rpc-protocol.md）
- `dev-process-control`: 增补"序号生成器约定"节（无 spec-delta，由子 change 直接合）

## 4. 影响面

- **后端**：`server/services/order_no.py`（核心）+ `server/api/orders.py`（调用方适配，去掉 db.commit 之前 next_order_no 的 commit）
- **测试**：`server/test_order_no.py` 增补 2 个 case + 新建 `server/test_order_no_atomic.py`
- **DB**：`order_no_seq` 表结构不变
- **前端**：无影响（order_no 通过 API 响应拿到）

## 5. 不在本 change 范围

- 改其他序列表（trading_day 序号、order_id 透传等）—— 另起 change
- `place_order` 其他逻辑（三屏障、状态机、push 链路）—— 越界禁止
- `add-config-validation` / `consolidate-rpc-parsers` 实施（仍是真 draft）
- 真实环境部署、QMT 柜台、msgpacket 协议本身

## 6. Tasks

- [ ] T1: 写 `spec-deltas/rpc-protocol.md` 增补 REQ-RPC-009
- [ ] T2: 改 `server/services/order_no.py` 单语句 UPSERT + 函数内 commit + 改 docstring
- [ ] T3: 改 `server/api/orders.py:place_order` 适配（去掉 next_order_no 后多余 commit）
- [ ] T4: 增补 `server/test_order_no.py` 2 个新 case（rollback 不回退 + 单语句验证）
- [ ] T5: 跑 `pytest server/test_order_no.py server/test_orders_api.py server/test_models.py -v` 全绿
- [ ] T6: 跑 `pytest server/test_reconcile.py` 验证对账流程不受影响
- [ ] T7: 合并 spec-delta 到 `openspec/specs/rpc-protocol/spec.md`
- [ ] T8: commit + push（v2ray 代理）
- [ ] T9: 归档：spec 已合并后 `mv openspec/changes/2026-06-21-order-no-atomic-upsert openspec/changes/archive/`
