# rpc-protocol — msgpacket RPC 客户端契约

## Purpose

后端通过 msgpacket 协议（YSWY）经 RabbitMQ 调用 QMT 柜台。
RPC 客户端统一封装：构造包、发送、等待 reply、超时、解析。
**所有业务代码**（api/）只能调用 `qry_*` / `ord_stk` / `cancel_order`，**不直接**碰 `RPClient.call()`。

## Requirements

### REQ-RPC-001: 客户端生命周期

- `get_rpc_client()` — 单例，启动时自动 connect + 启动 reply/push listener
- `close_rpc_client()` — 关闭连接（在 FastAPI shutdown 钩子中调用）
- 重复调用 `get_rpc_client()` 返回同一实例

### REQ-RPC-002: 调用语法

```python
pkt = await client.call(
    func,                      # 柜台函数名
    headers="field1,field2",   # 字段名（逗号分隔，对应 YSWY 包头）
    values={"field1": "...", "field2": "..."},  # 字段值
    timeout=30.0,              # 可选，默认 30s
)
```

`headers` 和 `values` 是必填（即便空也要传 `headers=""` 占位）。

### REQ-RPC-003: 响应解析

- RPC 响应统一 2 个结果集：
  - **RS1**: `{code: int, msg: str}` — 状态码 + 错误信息
  - **RS2**: `list[dict]` — 业务数据
- `code=0` 表示成功
- 业务函数 `_parse_*` 把 RS2 转成 TypedDict / Pydantic model

### REQ-RPC-004: 业务函数列表

| 函数 | RPC func | 解析器 | 返回 |
|---|---|---|---|
| `qry_asset` | `qry_asset` | `_parse_asset` | `{code, msg, list: [Asset]}` |
| `qry_orders` | `qry_orders` | `_parse_orders` | `{code, msg, list: [Order]}` |
| `qry_trades` | `qry_mch` | `_parse_trades` | `{code, msg, list: [Trade]}` |
| `qry_positions` | `qry_pos` | `_parse_positions` | `{code, msg, list: [Position]}` |
| `ord_stk` | `ord_stk` | `_parse_order_ack` | `{code, msg, list: [OrderAck]}` |
| `cancel_order` | `cancel_ord` | `_parse_order_ack` | `{code, msg, list: [OrderAck]}` |

### REQ-RPC-005: 超时与重试

- 默认超时 30s
- 超时后 reply 关联的 future 清理
- ❌ **不实现**重试（QMT 下单重试可能导致重复报单，副作用大）

### REQ-RPC-006: 错误处理

- 连接失败 → log + 返回 `{code: -1, msg: "RPC not connected", list: []}`
- 超时 → 同上 + log warning
- 解析失败 → log + 返回 `{code: -1, msg: "<error>", list: []}`

## Scenarios

### S-RPC-001: 正常查询

Given RPC 已连接，柜台在线  
When `qry_orders()`  
Then 30s 内返回 `{code: 0, msg: "", list: [Order...]}`

### S-RPC-002: 柜台断连

Given aio_pika.connect_robust 心跳超时  
When `qry_orders()`  
Then `connect_robust` 自动重连  
And 期间调用的 `_parse_*` 返回 `{code: -1, ...}`

### S-RPC-003: 错误传参

When `ord_stk(order_type="invalid")`  
Then 柜台返回 `{code: -100, msg: "order_type 非法", list: []}`  
And 后端原样透传

## Code Reference

- `server/rpc/client.py` — 客户端主体
- `server/rpc/client.py:23-24` — func → WS 频道映射（ord_cfm/trd_cfm）
- `server/rpc/client.py:530-571` — 业务函数实现
- `server/rpc/client.py:478+` — `_parse_ord_cfm`（push 专用，与查询解析器不同）

## Known Issues (from analysis)

- 🟡 8 个 `_parse_*` 解析器**没有统一 schema**（部分返回 dict，部分返回 TypedDict）
- 🟡 `cancel_order` 之前是**占位实现**（`client.call("cancel_ord")` 无参数）→ **本轮已修**
- 🟢 `ord_cfm` push 解析器与查询解析器不复用是合理的（字段确实不同）
