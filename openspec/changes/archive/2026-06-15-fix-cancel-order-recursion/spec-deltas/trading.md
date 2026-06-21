# Spec Delta — cancel order (trading)

## REQ-TRADE-003 撤单 (update)

### 实现细节

- `api/orders.py` 中避免路由函数与 `rpc.client` 导入名冲突
- 约定：导入时使用别名 `from rpc.client import cancel_order as rpc_cancel_order`
- DELETE handler 内部调用 `await rpc_cancel_order(order_id=order_id)`

### 变更前（bug）

```python
from rpc.client import ord_stk, cancel_order, qry_orders
# ...
@router.delete("/{order_id}")
async def cancel_order(order_id: str, ...):
    # cancel_order 指向自身，递归调用！
    ack = await cancel_order(order_id=order_id)
```

### 变更后（fix）

```python
from rpc.client import ord_stk, cancel_order as rpc_cancel_order, qry_orders
# ...
@router.delete("/{order_id}")
async def cancel_order(order_id: str, ...):
    ack = await rpc_cancel_order(order_id=order_id)
```
