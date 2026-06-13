# quotes — 行情数据分发

## Purpose

QMT 柜台通过 FANOUT exchange `quota.exchange` 推送行情快照。
`hq/hqserver.py` 订阅后双路转发：
- **(a)** 旧版兼容：republish 到 `quota.broadcast.exchange` (Topic, routing_key=stock_code)
- **(b)** 前端直连：内置 WebSocket :8765，JSON 推送

## Requirements

### REQ-QUOTE-001: 高吞吐消费

- aio-pika `iterator(no_ack=False)` + 显式 `message.ack()`
- 内部 `asyncio.Queue` 缓冲区（默认 maxsize=5000）做背压
- 4 个固定 worker 协程（`NUM_WORKERS` env 可调）
- 缓冲满后 aio-pika iterator 自然阻塞，防止内存爆

### REQ-QUOTE-002: 字段提取

- 原始 body 是 GBK 编码，格式：`stock_code|datetime|last_price|...`
- 切前两段即可得 `stock_code` 和 `last_price`，第三段不是数字则 `last_price=null`
- GBK 解码失败 → 回退 UTF-8（`errors="replace"`）

### REQ-QUOTE-003: 前端直连

- WebSocket 路径：`ws://<host>:8765`
- 客户端不发消息，服务器只 push
- 关闭连接后自动从 `_ws_clients` 移除
- 死连接（send 抛异常）清理

### REQ-QUOTE-004: 配置可调

- `HQ_RABBITMQ_URL` / `HQ_EXCHANGE_NAME` / `HQ_SOURCE_QUEUE` / `HQ_BROADCAST_EXCHANGE`
- `HQ_NUM_WORKERS` / `HQ_MAX_QUEUE_SIZE` / `HQ_PREFETCH_COUNT` / `HQ_WS_HOST` / `HQ_WS_PORT`
- 配置从 `server/.env` 加载（与 FastAPI 后端共享）

## Scenarios

### S-QUOTE-001: 正常行情推送

Given hqserver 已启动，RabbitMQ 行情队列有数据  
When QMT 推一条 `600030.SH|...|12.34|...`  
Then WS 客户端收到 `{"type":"quote","channel":"quote_update","data":{"stock_code":"600030.SH","last_price":12.34,"fields":[...],"body":"..."}}`

### S-QUOTE-002: 缓冲区满导致背压

Given `MAX_QUEUE_SIZE=5` 且 4 worker 全部被某慢任务卡住  
When RabbitMQ 推第 6 条  
Then `_consume` 协程的 `await task_queue.put(...)` 阻塞，RabbitMQ 端停止 ACK，下游被背压

### S-QUOTE-003: GBK 解码失败

When body 字节是合法 UTF-8 但非 GBK  
Then `stock_code` 用 UTF-8 解码，前端仍能收到（字段里替换坏字节）

### S-QUOTE-004: WS 客户端断开

Given 一个 WS 客户端连接  
When 它断网  
Then `send` 抛异常，连接被加入 `dead` 集合，函数结束前从 `_ws_clients` 移除

## Data Flow

```
RabbitMQ quota.exchange (FANOUT, durable=False)
        ↓ aio_pika iterator (no_ack=False)
asyncio.Queue (maxsize=5000)
        ↓ 4 workers
   (a) quota.broadcast.exchange (Topic, durable=True) ─── 兼容旧订阅
   (b) WebSocket :8765 ─── 前端直连
```

## Known Issues (from analysis)

- 🟢 hqserver 已有 18 个 mock-based 单元测试，**18/18 全绿**
- 🟡 `probe_hqserver.py` 临时探针脚本已删；如果需要可加进 `scripts/`
- 🟡 没有 reconnect-on-disconnect 的统一封装，靠 `aio_pika.connect_robust` 自带
