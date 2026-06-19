# 2026-06-19-rpc-link-topology — RPC 链路拓扑收紧（bind + publisher confirms）

## Problem

排查 RPC 链路时发现两个潜在故障点（用户也提到"没法正常和 RabbitMQ 请求应答交互"）：

1. **队列未显式绑定 exchange**：当前 `connect()` 只 `declare_queue`，**没有 bind 到 EXCHANGE_NAME**。
   当前能跑通只是因为 broker 端恰好已有 binding。一旦 broker 重置 / 切换环境，**请求会全部丢**，且无报错。

2. **publish 无 confirm**：直接 `exchange.publish(...)` 不等 broker ack。
   broker 重启 / 磁盘满 → **静默丢包**，调用方以为成功，实际 msg 丢失 → 超时后等不到 reply。

## Solution

最小修复 1 个文件 `server/rpc/client.py`：

### A. 显式 bind（REQ-RPC-007）

```python
req_q    = await self.channel.declare_queue(QUEUE_REQ, durable=True)
reply_q  = await self.channel.declare_queue(QUEUE_REPLY, durable=True)
push_q   = await self.channel.declare_queue(QUEUE_PUSH, durable=True)

await req_q.bind(self.exchange,   routing_key=QUEUE_REQ)
await reply_q.bind(self.exchange, routing_key=QUEUE_REPLY)
await push_q.bind(self.exchange,  routing_key=QUEUE_PUSH)
```

routing_key 用队列名（topic 也支持字面 key）。自包含不依赖 broker 预存 binding。

### B. Publisher Confirms（REQ-RPC-008）

```python
self.channel = await self.conn.channel(publisher_confirms=True)
```

aio_pika 的 `exchange.publish()` 在 `publisher_confirms=True` 时会自动等 ack。
需要**包一层超时**——5s 未 ack 则抛 RuntimeError 并清理 pending。

### C. connect 幂等守卫

```python
async def connect(self):
    if self.conn and not self.conn.is_closed:
        return
    ...
```

防止 FastAPI 重启 / 双启动 / 测试 setup 时重复 connect。

## Out-of-scope（独立 change 处理）

- push 同步 DB 操作改 async（涉及 push_handlers.py）
- listener 启动顺序优化（实际未出问题）
- qry_* 解析器统一 schema

## Risks

| 风险 | 缓解 |
|------|------|
| aio_pika 老版本不支持 `publisher_confirms` 参数 | requirements.txt 已锁定 ≥9.0，含此 API |
| bind 时 broker 端已有同名 queue 但参数不同（durable 不一致） | aio_pika 默认会校验，错误立刻抛 |
| 5s 超时过短 / 过长 | 做成 settings 字段可调 |

## Tests

新增 `server/test_rpc_link.py`：

1. `test_queues_bound_to_exchange` — mock aio_pika，验证 declare_queue + bind 各被调用，routing_key 正确
2. `test_publish_with_confirm` — 验证 publish 调用时 channel 已开 publisher_confirms
3. `test_publish_timeout_raises` — mock 让 publish 阻塞，验证 5s 抛 RuntimeError 且 pending 被清理
4. `test_connect_idempotent` — 第二次 connect() 不应重复 declare / bind
5. `test_reply_resolves_future` — 端到端：mock broker，call 后注入 reply → future resolve
6. `test_push_broadcasts_to_ws` — 端到端：mock broker，注入 push → ws_manager.broadcast 被调用

不依赖真实 broker，全 mock。

## Tasks

参见 tasks.md。