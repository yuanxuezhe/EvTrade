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

### REQ-RPC-007: 队列拓扑与绑定（v2 收紧）

- `connect()` 时**显式声明并绑定**三条 durable 队列到 `EXCHANGE_NAME`（topic）：
  - `EvTrade.Test.Req`    ← 发送 routing_key `EvTrade.Test.Req`
  - `EvTrade.Test.Reply`  ← 接收 routing_key `EvTrade.Test.Reply`
  - `EvTrade.Test.Push`   ← 接收 routing_key `EvTrade.Test.Push`
- 队列名直接作 routing_key（topic 通配 `*` / `#` 不依赖柜台侧预绑定）
- 重复 `connect()` 不报错（幂等）：已 connected 则直接返回
- 队列绑定失败（exchange 不存在 / 权限不足）→ 启动抛异常，不静默降级

### REQ-RPC-008: Publisher Confirms（v2 新增）

- channel 开启 `publisher_confirms=True`
- `exchange.publish()` 后**等 broker ack** 才返回（防 broker 重启/磁盘满导致静默丢包）
- 超时 5s 未 ack → 抛 `RuntimeError("publish unconfirmed")`，不挂起调用方
- RPClient 内部用 `_publish_confirm_timeout` 控制（默认 5s）

### REQ-RPC-009: 订单序号生成器原子性

`server/services/order_no.py:next_order_no(db)` 必须保证:

- **REQ-RPC-009.1** 原子自增, 实现允许两条路径:
  - (a) 理想方案: SQLite ≥ 3.35 单语句 `INSERT ... ON CONFLICT DO UPDATE ... RETURNING` 模式 (1 步)
  - (b) 兼容方案: SQLite ≥ 3.21 三步分离 `INSERT OR IGNORE` + `UPDATE` + `SELECT` 模式 (3 步, 函数内 commit)
  - 当前生产环境 Python 3.6.8 自带 SQLite 3.21.0, **必须使用方案 (b)**; 升级 Python 或 libsqlite3 后可切到 (a)
- **REQ-RPC-009.2** 函数内自动 commit (破坏旧"调用方负责 commit"约定), 消除"调用方异常回滚导致序号回退"风险
- **REQ-RPC-009.3** 返回 8 位数字字符串 '10000001'-'99999999', 达到上限时 raise RuntimeError
- **REQ-RPC-009.4** docstring 必须真实描述实现 (不得注释与代码不符)
- **REQ-RPC-009.5** 跨进程/线程安全 (依赖 SQLite 串行写入)

**旧约定废弃**:
- ❌ 调用方负责 commit → ✅ 函数内自动 commit
- ❌ 3 步分离语句 (INSERT OR IGNORE + UPDATE + SELECT) → ✅ 单语句 UPSERT

**调用方适配**:
- `server/api/orders.py:place_order` 调用 `next_order_no` 后 **不应** 立即 commit (函数内已 commit)
- `order_no` 跳号是 acceptable (下单失败 / 序号已 +1 但 Order 未入库, 与生产实际一致)

### REQ-RPC-010: client.py 拆分（phase-2）

677→76 行 facade 兼容垫片 + 4 个单一职责子模块：
- `server/rpc/transport.py` (403) — RPClient 传输层（connect / call / listeners / push / 全局单例 + 4 utility）
- `server/rpc/parsers_common.py` (109) — 通用响应解析（_select_rs / _parse_code_msg / _iter_rows / _to_* / _empty）
- `server/rpc/parsers_business.py` (126) — 业务特定解析（_parse_asset / _parse_orders / _parse_trades / _parse_positions / _parse_order_ack）
- `server/rpc/handlers.py` (100) — 业务 RPC 入口（qry_asset / qry_orders / qry_trades / qry_positions / ord_stk / cancel_order）

**契约**：
- 既有 `from rpc.client import ...` 仍可解析（13 import 站点全过）
  - `test_rpc.py` / `test_rpc_link.py` 用 `from rpc.client`（cwd=server）
  - `api/orders.py` / `main.py` / `services/reconcile.py` 用 `from server.rpc.client`
  - 全部符号在 facade re-export（RPClient / get_rpc_client / close_rpc_client / RABBITMQ_URL / EXCHANGE_NAME / QUEUE_* / _PUSH_CHANNEL / 6 业务函数）
- 子模块间单向依赖：transport ← handlers ← parsers_business ← parsers_common；无环
- `transport._iter_push_rows` 是 push 链路专用的行提取器（与 parsers_common._iter_rows 思路不同：不做类型转换），留在 transport

### REQ-RPC-011: 推送类型 → WS channel 映射表（v1）

- 位置：`server/rpc/transport.py::_PUSH_CHANNEL`
- 映射：
  - `ord_cfm` → `order_update`
  - `trd_cfm` → `trade_update`
  - `pos_cfm` → `position_update`
  - `ast_cfm` → `asset_update`
- 用途：`RPClient._listen_pushs` 收到 push 后查表决定 WS 频道
- 未知 func：log warning + skip（不广播）

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

### S-RPC-004: 队列绑定（v2）

Given 服务启动 `connect()`  
When 检查 broker 队列表  
Then `EvTrade.Test.Req` / `EvTrade.Test.Reply` / `EvTrade.Test.Push` 均存在  
And 三条队列的 binding source exchange = `EXCHANGE_NAME`，routing_key = 各自队列名

### S-RPC-005: Publisher Confirm 超时（v2）

Given broker 停止 ack（mock 故障）  
When `call("qry_ast")`  
Then 5s 内抛 `RuntimeError("publish unconfirmed")`  
And `pending` dict 不残留（避免后续应答误匹配）

## Code Reference

- `server/rpc/client.py` — 客户端主体
- `server/rpc/client.py:23-24` — func → WS 频道映射（ord_cfm/trd_cfm）
- `server/rpc/client.py:530-571` — 业务函数实现
- `server/rpc/client.py:478+` — `_parse_ord_cfm`（push 专用，与查询解析器不同）

## Known Issues (from analysis)

- 🟡 8 个 `_parse_*` 解析器**没有统一 schema**（部分返回 dict，部分返回 TypedDict）
- 🟡 `cancel_order` 之前是**占位实现**（`client.call("cancel_ord")` 无参数）→ **本轮已修**
- 🟢 `ord_cfm` push 解析器与查询解析器不复用是合理的（字段确实不同）
