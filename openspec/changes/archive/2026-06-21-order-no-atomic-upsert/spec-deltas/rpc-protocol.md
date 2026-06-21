# REQ-RPC-009: 订单序号生成器 (ADDED)

## ADDED Requirements

### REQ-RPC-009: 订单序号生成器原子性

The `next_order_no(db)` function in `server/services/order_no.py` **MUST** guarantee:

- **REQ-RPC-009.1**: 单语句原子自增, 使用 SQLite ≥ 3.35 `INSERT ... ON CONFLICT DO UPDATE ... RETURNING` 模式
- **REQ-RPC-009.2**: 函数内自动 commit (破坏旧"调用方负责 commit"约定), 消除"调用方异常回滚导致序号回退"风险
- **REQ-RPC-009.3**: 返回 8 位数字字符串 '10000001'-'99999999', 达到上限时 raise RuntimeError
- **REQ-RPC-009.4**: docstring 必须真实描述实现 (不得注释与代码不符)
- **REQ-RPC-009.5**: 跨进程/线程安全 (依赖 SQLite 串行写入)

## 旧约定废弃

- ❌ ~~调用方负责 commit~~ → ✅ 函数内自动 commit
- ❌ ~~3 步分离语句 (INSERT OR IGNORE + UPDATE + SELECT)~~ → ✅ 单语句 UPSERT

## 影响

- `server/api/orders.py:place_order` 调用方 **不应** 在 `next_order_no` 之后立即 commit
  (commit 已在函数内完成, 重复 commit 幂等无副作用但浪费 IO)
- `order_no` 跳号是 acceptable (下单失败 / 序号已 +1 但 Order 未入库, 与生产实际一致)

## 测试

- `pytest server/test_order_no.py` — 序号唯一性 + 8 位字符串
- `pytest server/test_order_no.py::test_atomic_no_callback_commit` — 验证回滚不回退
- `pytest server/test_orders_api.py` — 下游 place_order 不受影响
