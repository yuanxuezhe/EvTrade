# Fix: test_place_async 6 fail + fixture 不删表数据

> 用户拍板 2026-08-27：P1-1 第 2 刀。Why 详见 CLAUDE.md § 八"历史失败归属"表。
> 用户硬规则 2026-08-27：**禁止清表数据**，测试 fixture 改为隔离 trd_date + 高位 order_no 区间 + monkeypatch `_get_active_trd_date`。

## Why

`server/tests/test_place_async.py` 6 个 fail 是 **fixture 期望过时 + fixture 删除生产数据** 两类问题叠加：

### 问题 1：fixture 删除生产数据（用户硬规则违规）

| fixture 行为 | 现状 | 用户硬规则 |
|---|---|---|
| `DELETE FROM orders` | 每次测试清空 | ❌ 违规 |
| `ALTER TABLE orders AUTO_INCREMENT = 1` | 重置自增 | ❌ 违规 |
| `SysStatus.delete_one(id=1)` + `SysStatus.upsert_one({...}, id=1)` | 覆盖生产 sys_status | ❌ 违规 |
| `DELETE FROM users WHERE LOCATE('_', username) > 0 ...` | 清测试用户 | ✅ OK（注释已排除 admin/trader） |

**生产数据现状（2026-08-27 实测）**：
- `orders` 表 1 行（trd_date=`20260718`）
- `sys_status` 表 1 行（生产日初状态）

跑测试会清掉这些。

### 问题 2：6 个 test 期望过时（v11 broker 字典对齐后）

| Fail | 测试期望 | 代码实际（v11 后） |
|---|---|---|
| `test_submit_rpc_success_updates_status_50_and_pushes` | `status=50` + `status_msg="已报"` | `_submit_rpc_async` ack.code=0 时**不写 status_msg**也不写 status=50，留给 `services/push/ord.py:98` 处理 broker ord_cfm 异步推送 |
| `test_submit_rpc_broker_reject_updates_status_57_with_cancel_volume` | `status=57`（ack.code=1） | transport 层 `_handle_ord_stk_reply_junk` 接管废单路径（不在 place.py 写） |
| `test_submit_rpc_exception_updates_status_57_and_pushes` | `status=57` + `status_msg="RPC 失败..."` | 实际 status=48（不写） + msg 没改（异常路径不更新 DB，依赖 broker push） |
| `test_submit_rpc_payload_includes_task_id_and_strategy` | payload 含 `task_id` / `strategy` 字段 | `_to_order_out` 不含这 2 字段（v91.4 前端 usePush 改造后已废弃） |
| `test_endpoint_creates_task_and_returns_immediately` | `status_msg == "未报"` | 实际 `status_msg == ""`（v11 broker 字典对齐后，48 状态的 msg 改为前端 display 决定） |

### 关键代码证据

`server/api/orders/place.py:241-247`：
```python
# 不解 ack.code, 不写 Order (broker ord_cfm push 会异步处理真实状态)
#      transport._handle_ord_stk_reply_junk 已在另一个线程处理了 code!=0 废单路径
#      code==0 应答: broker_order_id 此时空, ord_cfm 异步推来时才有
try:
    ack_code = int(ack.get("code", -1)) if isinstance(ack, dict) else -1
except (TypeError, ValueError):
    ack_code = -1
log.info("_submit_rpc_async: order_no=%s ack received (code=%s). ...", order_no, ack_code)
```

**`_submit_rpc_async` 在 v11 后只 log 不写 DB**，全部状态更新由 push handler 接管。

## What

**单 commit 单目的**（按 v6 规范）：纯测试代码改动，零生产代码改动，零数据风险。

### 改动 1：fixture 改为不删数据

1. `db()` fixture：去掉 `DELETE FROM orders` + `ALTER TABLE AUTO_INCREMENT = 1`，纯 yield session
2. `trader()` fixture：去掉 `SysStatus.delete_one/upsert_one`（不重置 sys_status）
3. 新增 `mock_trd_date()` fixture：`monkeypatch server.repo.orders._get_active_trd_date` 返回 `'99990718'`（隔离 trd_date）
4. trader fixture 改用 `Users.upsert_one(...)` 模式（首次 add，重复跑 idempotent）

### 改动 2：6 个 test 重写对齐 v11 代码

| 测试 | 改前期望 | 改后期望 |
|---|---|---|
| `test_submit_rpc_success_updates_status_50_and_pushes` | `status=50` + `status_msg="已报"` | `status=48`（未变）+ `status_msg="未报"`（fixture 初始值）+ 验证 ord_cfm 推送走 `services/push/ord.py` 而非 `_submit_rpc_async` |
| `test_submit_rpc_broker_reject_updates_status_57_with_cancel_volume` | `status=57` | 验证 transport cache 接管（mock transport._handle_ord_stk_reply_junk）+ `_submit_rpc_async` 不写 status |
| `test_submit_rpc_exception_updates_status_57_and_pushes` | `status=57` + RPC 失败 msg | 改为验证 **fallback 路径**：异常时 `_submit_rpc_async` **写 status=57 + status_msg**（line 230-232 是 fallback 路径，写 status=57 + ws push） |
| `test_submit_rpc_payload_includes_task_id_and_strategy` | payload 含 task_id / strategy | 改为验证 payload **不**含 task_id / strategy（v91.4 后废弃），改为验证 `order_id` / `traded_volume` / `cancelled_volume` 等基础字段 |
| `test_endpoint_creates_task_and_returns_immediately` | `status_msg == "未报"` | `status_msg == ""`（v11 后空字符串，由前端 formatStatus 显示） |

### 改动 3：测试写入用隔离 trd_date

`_make_order` 改默认 `trd_date="99990718"`，**跟生产 `trd_date=20260718` 隔离**。

## 不做什么

- **不动** `server/api/orders/place.py`（代码行为是 v11 后设计正确）
- **不动** `server/services/push/ord.py`（已正确处理 broker ord_cfm）
- **不动** `server/repo/orders.py:_get_active_trd_date`（monkeypatch 替换）
- **不动** DB 任何数据（用户硬规则）
- **不动** `server/tests/test_orders_cancel.py` / `server/tests/test_v78_skip_rebroadcast.py`（P1-1-③/④ 处理）

## 验证 (v6 完成自查)

- [ ] `pytest server/tests/test_place_async.py -v` → 5 passed / 0 failed（删 1 个 payload test 因为业务已废弃）
- [ ] `pytest hq/ server/tests/ tests/` → 130 collected / 128 passed / 2 failed（12-6=6 fail 剩余，但 place_async 5 个已修）
- [ ] **生产数据未变**：`SELECT COUNT(*) FROM orders` 仍 = 1
- [ ] `git diff --stat` 显示改动**仅** `server/tests/test_place_async.py`
- [ ] commit message: `test(orders): place_async 改 fixture 不删表 + 6 个 test 对齐 v11 后设计 (P1-1 第 2 刀)`
- [ ] 归档：`mv openspec/changes/2026-08-27-test-place-async-fixture-sync openspec/changes/archive/`

## 数据安全（用户硬规则 2026-08-27）

- 不动 MySQL 任何表/列/行
- fixture 不写 `DELETE FROM` / `TRUNCATE` / `ALTER TABLE AUTO_INCREMENT`
- 隔离用 `trd_date='99990718'` 高位字符串（不会跟生产 `202608xx` 冲突）
- 测试 trader 用户名 `t_place_v77` 已加下划线，fixture finalizer 注释排除 admin/trader
