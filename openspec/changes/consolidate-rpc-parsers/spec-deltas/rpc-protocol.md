# Spec Delta — consolidate-rpc-parsers → rpc-protocol

## MODIFIED Requirements

### REQ-RPC-003（重写）

**响应解析**：

RPC 响应统一用 Pydantic `BaseModel` 解析。

```python
class RpcResponse(BaseModel, Generic[T]):
    code: int           # 0=成功
    msg: str            # 错误描述
    list: List[T]       # 业务数据，Pydantic 实例
```

- `T` 是该 RPC 对应的响应模型（`OrderResponse` / `TradeResponse` / `AssetResponse` / `PositionResponse` / `OrderAckResponse`）
- 业务函数签名：`async def qry_orders() -> RpcResponse[OrderResponse]`
- 前端契约不变（序列化后字段名/类型一致）

### REQ-RPC-004（更新返回类型）

| 函数 | RPC func | 返回类型 |
|---|---|---|
| `qry_asset` | `qry_asset` | `RpcResponse[AssetResponse]` |
| `qry_orders` | `qry_orders` | `RpcResponse[OrderResponse]` |
| `qry_trades` | `qry_mch` | `RpcResponse[TradeResponse]` |
| `qry_positions` | `qry_pos` | `RpcResponse[PositionResponse]` |
| `ord_stk` | `ord_stk` | `RpcResponse[OrderAckResponse]` |
| `cancel_order` | `cancel_ord` | `RpcResponse[OrderAckResponse]` |

## ADDED Requirements

### REQ-RPC-007: 异常字段容错

- 响应字段缺失时使用 `Field(default=...)`，**不抛** ValidationError
- 类型不匹配时记录 warning 日志，**降级**为默认值
- `code` 非 0 时 `list` 可为空

## REMOVED Requirements

无（旧的 `_parse_*` 函数不是 spec 要求，是实现细节）
