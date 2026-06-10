# Server · 07 · WebSocket 推送（WS Manager）

> 文件：`server/ws/manager.py` · `server/ws/__init__.py`

## 1. 通道定义

```python
class WSManager:
    def __init__(self):
        self.active_connections = {
            "order_update":    set(),
            "trade_update":    set(),
            "position_update": set,
            "asset_update":    set(),
        }

ws_manager = WSManager()   # 单例
```

4 个命名通道，订阅者通过连接时指定：

| 通道 | 推送内容 | 触发点 |
|------|----------|--------|
| `order_update` | 委托状态变化 | XtQuant `on_stock_order` / RPC push |
| `trade_update` | 成交回报 | XtQuant `on_stock_trade` / RPC push |
| `position_update` | 持仓变化 | 成交联动 / RPC push |
| `asset_update` | 资金变化 | 成交联动 / 定时快照 |

## 2. 方法

### 2.1 `async connect(websocket, channel="order_update")`
- `await websocket.accept()`
- 写入 `self.active_connections[channel]`
- 通道不存在时 `setdefault` 创建

### 2.2 `disconnect(websocket, channel="order_update")`
- 从 set 中 discard（无异常）

### 2.3 `async broadcast(channel, message: dict)`
- 遍历该通道所有连接
- `await connection.send_json(message)`
- 发送失败 → 收集到 `dead_connections`，再统一 discard
- 静默失败（不抛）

## 3. 单例
```python
ws_manager = WSManager()
```
进程内唯一。

## 4. 接入点（未挂载）

### 4.1 后端
`server/main.py` **当前未注册** WebSocket 路由。预留方案：
```python
@app.websocket("/ws/{channel}")
async def ws_endpoint(websocket: WebSocket, channel: str):
    await ws_manager.connect(websocket, channel)
    try:
        while True:
            await websocket.receive_text()  # 阻塞保活
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, channel)
```

### 4.2 触发广播
- `XtQuant` 回调内：`asyncio.create_task(ws_manager.broadcast("order_update", {...}))`
- `RPC push` 消费协程：解包后 `ws_manager.broadcast(...)`
- 注意：回调线程是 SDK 线程，需用 `asyncio.run_coroutine_threadsafe` 投递到 event loop

## 5. 前端封装

`client/src/api/index.js` 已预留：
```js
export function createWSConnection(channel = 'order_update') {
  const wsUrl = `ws://${window.location.host}/ws/${channel}`
  const ws = { value: null }
  const messages = []
  let connected = false

  function connect() {
    ws.value = new WebSocket(wsUrl)
    ws.value.onopen  = () => { connected = true }
    ws.value.onmessage = (e) => { messages.push(JSON.parse(e.data)) }
    ws.value.onclose = () => { connected = false }
  }
  // ...
  return { ws, messages, connected, disconnect }
}
```
> 当前**无视图实际调用** `createWSConnection`，仅占位。订单状态依靠轮询 `GET /api/orders`（`Trade.vue` 5s 间隔）。

## 6. 消息格式（建议）

```json
{
  "type": "order_update",
  "data": {
    "order_id": "8a3c1b0e",
    "status": "filled",
    "traded_volume": 100,
    "traded_price": 11.10
  },
  "ts": "2026-06-09T09:35:25.123Z"
}
```

## 7. 待完善

| 项 | 建议 |
|----|------|
| 心跳 | 服务端周期性 send `{"type":"ping"}`，客户端 30s 未收到主动断开 |
| 鉴权 | WS 握手时校验 JWT（`?token=...` 或首条消息携带） |
| 退避重连 | 客户端指数退避，最大 30s |
| 订阅粒度 | 支持订阅特定 `stock_code` 过滤 |
| 多通道合并 | 单连接可订阅多个 channel |
| 背压 | 慢消费者断开，避免内存堆积 |
