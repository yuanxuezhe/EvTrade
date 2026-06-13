# Consolidate RPC parsers

## 1. Why

`server/rpc/client.py` 中有 8 个 `_parse_*` 解析器：
- `_parse_asset`, `_parse_orders`, `_parse_trades`, `_parse_positions`（查询路径）
- `_parse_order_ack`（下单/撤单应答）
- `_parse_ord_cfm`, `_parse_trd_cfm`（push 路径）
- `_parse_xxx`（其他零散）

问题：
- 返回类型不一致（部分 dict 部分 TypedDict）
- 字段映射散落（每个函数重新写 `p.get("xxx", default)`）
- 添加新 RPC 要复制粘贴模板
- 单元测试覆盖差

## 2. What

### 2.1 统一 schema

- 用 Pydantic `BaseModel` 定义响应 schema：`AssetResponse`, `OrderResponse`, `TradeResponse`, `PositionResponse`, `OrderAckResponse`
- 解析器只做 `dict → BaseModel` 转换，业务代码拿到的就是 Pydantic 实例
- 异常字段用 `Field(default=...)` 容错

### 2.2 统一解析入口

```python
def _parse_rpc_response(pkt, rs1_model=BaseAck, rs2_model=BaseModel) -> RpcResponse:
    """把 msgpacket 回复包解析为统一 RpcResponse{code, msg, list}"""
```

### 2.3 业务函数返回类型升级

```python
async def qry_orders() -> RpcResponse[OrderResponse]: ...
async def ord_stk(...) -> RpcResponse[OrderAckResponse]: ...
```

### 2.4 push 解析器复用

`ord_cfm` push 消息结构与 `qry_orders` 不同（多 status/traded_volume 等），用单独的 `OrderPushEvent` model，**不复用** OrderResponse。

## 3. 影响面

- `server/rpc/client.py` — 重构解析层
- `server/api/{orders,trades,asset,positions}.py` — 改成 `.model_dump()` 或直接传 BaseModel
- `server/models/types.py` — 增加 Pydantic 响应模型
- 前后端契约不变（响应字段名/类型保持）

## 4. Spec Deltas

`rpc-protocol/spec.md`:
- REQ-RPC-003 响应解析：明确 Pydantic 解析
- REQ-RPC-004 业务函数表：增加返回类型
- 移除"返回类型不一致"Known Issue

## 5. Tasks

- [ ] 定义 Pydantic 响应模型
- [ ] 实现统一 `_parse_rpc_response` 入口
- [ ] 重写 6 个业务 `_parse_*` 解析器
- [ ] api 层改造：直接用 BaseModel 字段
- [ ] 写单测覆盖 RS1/RS2 异常路径
- [ ] 更新 spec
- [ ] pytest 全绿
- [ ] commit + push
