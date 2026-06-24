# WS-Protocol 能力 spec（新建）

## Purpose

WebSocket 实时推送协议 — 5 通道、payload 协议、双向心跳、指数退避、模块边界。

## Requirements

### REQ-WS-001: 5 通道 + URL

- **端点**：`ws://host:port/ws/positions`
- **5 通道**：`order_update` / `trade_update` / `position_update` / `asset_update` / `quote_update`
- 详见 `ws-protocol/spec.md`

### REQ-WS-002: payload 协议

```json
{
  "channel": "order_update",
  "action": "open" | "update" | "status",
  "data": { /* row 字段 */ }
}
```

### REQ-WS-003: 双向心跳 (M-005)

- 客户端每 30s 发 `{"type":"ping"}`
- 服务端 30s 内必须回 `{"type":"pong"}`
- 服务端 60s 收不到 ping → 关闭连接 (4408)

### REQ-WS-004: 指数退避重连

- `RECONNECT_BASE_DELAY = 1000ms`
- `RECONNECT_MAX_DELAY = 30000ms`
- 失败一次: delay *= 2 (cap 30s)；首次 1s/2s/4s/8s/16s/30s/30s...

### REQ-WS-005: 模块边界（phase-2）

- `client/src/stores/ws.js` — Pinia store facade（47 行）
- `client/src/stores/ws_heartbeat.js` — 连接/重连/心跳/退避
- `client/src/stores/ws_dispatch.js` — payload 解析 + 5 通道 handler

详见 `ws-protocol/spec.md` REQ-WS-001..005 完整定义
