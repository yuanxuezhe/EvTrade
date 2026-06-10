# Server · 05 · 异步 RPC 客户端（RPC over RabbitMQ + MsgPacket）

> 文件：`server/rpc/client.py`
> 协议：见 `README.md`（仓库根目录 MsgPacket Python API 文档）

## 1. 通信拓扑

```
┌──────────────┐                ┌────────────────────┐                ┌──────────────┐
│  FastAPI     │  publish       │  msgpacket.exchange │  route         │  柜台/       │
│  (本服务)    │ ─────────────▶ │  (topic, durable)    │ ─────────────▶ │  模拟服务    │
│              │                │                      │                │              │
│  exchange.   │ ◀───────────── │  EvTrade.Test.Reply  │ ◀───────────── │  异步应答    │
│  publish     │  msg_id 匹配   │  EvTrade.Test.Push   │  fire-and-forget│              │
└──────────────┘                └────────────────────┘                └──────────────┘
```

## 2. 常量
```python
RABBITMQ_URL = "amqp://192.168.10.2:5672/"
EXCHANGE_NAME = "msgpacket.exchange"
QUEUE_REQ    = "EvTrade.Test.Req"     # 客户端 → 柜台
QUEUE_REPLY  = "EvTrade.Test.Reply"   # 柜台 → 客户端（按 msg_id 匹配）
QUEUE_PUSH   = "EvTrade.Test.Push"    # 柜台 → 客户端（推送）— 当前未消费
```

## 3. 类 `RPClient`

### 3.1 状态
| 字段 | 类型 | 说明 |
|------|------|------|
| `url` | str | AMQP URL |
| `conn` | `aio_pika.Connection` | 健壮连接 |
| `channel` | `aio_pika.Channel` | 单通道 |
| `exchange` | `aio_pika.Exchange` | topic 交换机 |
| `reply_queue` | `aio_pika.Queue` | 应答队列 |
| `pending` | `dict[msg_id, Future]` | 等待中的请求 |

### 3.2 `async connect()`
- `aio_pika.connect_robust(url)`
- 声明 topic 交换机 `msgpacket.exchange`（durable）
- 声明队列 `EvTrade.Test.Req` 和 `EvTrade.Test.Reply`（均 durable）
- `asyncio.ensure_future(self._listen_replies())` 启动应答监听

### 3.3 `async _listen_replies()`
- 遍历 reply_queue 消息
- 解析为 `MsgPacket`，取 `msg_id().strip()`
- 在 `self.pending` 查找 future，`set_result(pkt)` 唤醒调用方
- 找不到 `msg_id` 时打印后忽略（多客户端场景的健壮性）

### 3.4 `async call(func: str) -> MsgPacket`
- 构造 `MsgPacket(MSG_TYPE_REQUEST, "V1.0")`
- 设置 `func`、`msg_id`（UUID4）
- `finalize()` 序列化
- 注册 `pending[msg_id] = loop.create_future()`
- `exchange.publish(Message(body=wire_data), routing_key=QUEUE_REQ)`
- `await asyncio.wait_for(future, timeout=30)` 等待应答

> ⚠️ 调用前**必须**在 `finalize()` 之前 `set_msg_id`，否则 `set_msg_id` 不会写进编码后的字节流。

### 3.5 `async close()`
- 关闭 connection（channel 自动释放）

## 4. 全局单例

```python
_rpc_client: Optional[RPClient] = None

async def get_rpc_client() -> RPClient:
    global _rpc_client
    if _rpc_client is None:
        _rpc_client = RPClient()
        await _rpc_client.connect()
    return _rpc_client

async def close_rpc_client():
    global _rpc_client
    if _rpc_client:
        await _rpc_client.close()
        _rpc_client = None
```

## 5. 业务封装

### 5.1 查询函数（都 `await call(func)` → 解析多结果集）

| 函数 | RPC func | 解析器 | 关键字段 |
|------|----------|--------|----------|
| `qry_asset()` | `qry_ast` | `_parse_asset` | cash / frozen_cash / market_value / total_asset |
| `qry_orders()` | `qry_ord` | `_parse_orders` | order_id / stock_code / order_volume / traded_volume / traded_price / order_status / order_type / direction / order_time |
| `qry_trades()` | `qry_mch` | `_parse_trades` | trade_id / order_id / stock_code / direction / volume / price / trade_time |
| `qry_positions()` | `qry_pos` | 内联解析 | stock_code / stock_name / volume / avl_amt / avg_price / market_value |

### 5.2 解析器共性
- 用 `pkt.result_set_count()` 循环，`next_result_set()` 切换
- `reset_cursor()` + `fetch_next()` 遍历行
- `get_value_str("key")` 读值，缺失回退到备选 key（容错）：
  - `volume` ↔ `order_volume` ↔ `traded_volume`
  - `price` ↔ `traded_price` ↔ `avg_price`
  - `available` ↔ `avl_amt`
  - `order_status` ↔ `status`
- 类型转换时容错（`int(s or 0)`, `float(s or 0.0)`）

### 5.3 交易函数

#### `async ord_stk(stock_code, volume, price_type, price, direction) -> dict`
- **fire-and-forget**（XtQuant 的 `ord_stk` 柜台不回包）
- 构造带 5 个 header 的请求包：
  ```
  headers = "stock_code,volume,price_type,price,direction"
  ```
- 直接 `publish` 后立即返回临时单号
- 返回值：`{ "order_id": msg_id[:8], "status": "pending" }`
- ⚠️ 真实状态需通过 push 队列（`EvTrade.Test.Push`）异步更新

#### `async cancel_order(order_id) -> dict`
- 调 `await client.call("cancel_ord")`（请求体留空）
- 返回：`{ "order_id": order_id, "status": "cancelled" }`
- ⚠️ 当前没有把 order_id 写入请求体，是占位实现

## 6. 错误处理

| 场景 | 行为 |
|------|------|
| `RPClient.call` 超时 30s | `asyncio.TimeoutError` 抛出到调用方 |
| 解析异常 | 解析器不抛错，跳过该行（部分容错） |
| `ord_stk` 异常 | 在 `orders.py` 包装为 `500` HTTPException |
| `qry_*` 异常 | 上层 `api/*.py` `print` 后返回 `[]` 或全 0 |

## 7. 消息包结构（参考 README.md）

```
偏移 0  : magic[4]     = "YSWY"
偏移 4  : crc32[4]     = LE
偏移 8  : body_len[4]  = LE
偏移 12 : msg_header_t (72 字节) — 含 func / msg_id / timestamp / type / format / version
偏移 83 : body[]       = 柔性数组（header + rows × 多结果集）
```

## 8. 待完善

- 消费 `EvTrade.Test.Push` 队列，触发订单状态实时推送（WS 通道已就绪）
- `cancel_order` 真正传 order_id
- 重连 / 错误退避策略（当前 `connect_robust` 已处理重连，但 channel 异常未做重声明）
- `qry_positions` 解析仅取必要字段，未做单位 / 缩放处理
