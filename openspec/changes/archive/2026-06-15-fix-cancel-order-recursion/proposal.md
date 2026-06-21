# Fix cancel order recursion

## 1. Why

`server/api/orders.py:32` 导入 `from rpc.client import cancel_order`，但第 255 行定义同名路由处理函数 `async def cancel_order(order_id, ...)`，覆盖了模块级导入名。第 269 行：

```python
ack = await cancel_order(order_id=order_id)
```

实际调用的是**路由处理函数自身**而非 `rpc.client.cancel_order`，导致无限递归 → `RecursionError` 堆栈溢出。每次撤单必然崩溃。

## 2. What

### 2.1 修复方案

**方案 A（推荐）**：导入时别名，最小改动：

```python
from rpc.client import ord_stk, cancel_order as rpc_cancel_order, qry_orders
```

第 269 行改为：

```python
ack = await rpc_cancel_order(order_id=order_id)
```

**方案 B**：改用模块导入：

```python
from rpc import client as rpc_client
# ...
ack = await rpc_client.cancel_order(order_id=order_id)
```

推荐 A：改动最小，只有 2 行。

### 2.2 验证

- 调用 `DELETE /api/orders/{id}` 应正常返回撤单 ack
- 不应出现 `RecursionError`
- 现有 tests 全绿

## 3. 影响面

- `server/api/orders.py:32` — 改 import 别名
- `server/api/orders.py:269` — 改用别名调用
- 不影响前端、不影响 RPC 协议

## 4. Spec Deltas

`trading/spec.md`:
- REQ-TRADE-003 撤单：补充实现细节（import 别名约定）

## 5. Tasks

- [ ] 改 import：`cancel_order as rpc_cancel_order`
- [ ] 改调用：`await rpc_cancel_order(order_id=order_id)`
- [ ] 写单测 `server/test_orders_api.py::test_cancel_order_calls_rpc`
- [ ] pytest 全绿
- [ ] 手动验证：curl DELETE /api/orders/{id}
- [ ] commit: `fix(api): cancel_order 递归调用改为 RPC 调用`
