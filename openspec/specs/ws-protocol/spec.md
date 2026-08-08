# ws-protocol — WebSocket 推送协议（客户端视角）

## Purpose

EvTrade 前端通过 **7 个 WebSocket channel** 接收实时推送：

- 4 个**业务 channel**（`order_update` / `trade_update` / `position_update` / `quote_update`）走**后端** `/ws/<channel>`，复用 JWT 鉴权
- 1 个**行情 channel**（`quote_update`）直连 hqserver（端口 8765），不走后端转发
- 1 个**策略 channel**（`strategy_update`）走**后端**，由 `server/services/strategy/engine.py` 推送 `regime_changed` / `grid_triggered` / `regime_cooldown` 等事件
- 1 个**系统 channel**（`system_update`）走**后端**，由日初对账（`server/api/admin/sys_status.py`）+ RPC 健康监测（`server/services/rpc_health.py`）推送 `system_status_change` / `rpc_status` / `asset_update`（v117 合并 init_completed）
- 1 个**任务进度 channel**（`task_progress_update`）走**后端**，v91.4 起 ScriptTask.vue 详情实时刷新

> **T0 策略频道** `t0_strategy_update`：常量定义在 `server/services/strategy/t0/engine.py:42`（`T0_WS_CHANNEL = "t0_strategy_update"`），但**未注册到 ws_manager.active_connections**（v92 起独立频道；后续若启用需补注册）

本能力涵盖 **客户端** 侧 WS 连接管理、心跳、重连和分发约定。服务端的 push 链路（`server/services/push_handlers.py`）归属 `push` 能力。

phase-2 把 `client/src/stores/ws.js`（347 行 3 类职责）拆分为:
- `ws_heartbeat.js` — 连接 / 重连 / 心跳
- `ws_dispatch.js`  — payload → store 业务分发 + 通知
- `ws.js` (facade)  — Pinia store 装配（~50 行）

## Requirements

### REQ-WS-001: 7 个 channel + URL 约定

客户端连接以下 7 个 channel：

| Channel | URL 模式 | 鉴权 | 触发源 |
|---|---|---|---|
| `order_update` | `{proto}://{host}/ws/order_update?token={jwt}` | JWT (query) | 后端 `push_handlers` ord_cfm / API 直接 broadcast |
| `trade_update` | `{proto}://{host}/ws/trade_update?token={jwt}` | JWT (query) | 后端 `push_handlers` trd_cfm |
| `position_update` | `{proto}://{host}/ws/position_update?token={jwt}` | JWT (query) | 后端 `push_handlers` pos_push（v118+ broker 推送）|
| `quote_update` | `{proto}://{QUOTE_WS_HOST}/` | **无**（hqserver 直连）| hqserver 行情（FANOUT）|
| `strategy_update` | `{proto}://{host}/ws/strategy_update?token={jwt}` | JWT (query) | `server/services/strategy/engine.py` 策略事件 |
| `system_update` | `{proto}://{host}/ws/system_update?token={jwt}` | JWT (query) | 日初对账 + RPC 健康监测 |
| `task_progress_update` | `{proto}://{host}/ws/task_progress_update?token={jwt}` | JWT (query) | `server/services/script_strategy/` 任务进度 |

- `proto` = `wss` (https) 或 `ws` (http)
- `host` = 当前页面 host（如 `localhost:50998`）
- `QUOTE_WS_HOST` = `VITE_QUOTE_WS_URL` 环境变量 或 `{hostname}:8765`
- `token` 取自 `localStorage.getItem('evtrade-token')`

> **实际注册清单**见 `server/ws/manager.py:49-64` `active_connections` dict。

### REQ-WS-002: payload 协议

服务端把柜台 push 包（func + rows）原样转 JSON：

```json
{
  "type": "ord_cfm" | "trd_cfm" | "pos_cfm" | "ast_cfm" | "quote" | "ping" | "pong"
      | "system_status_change" | "rpc_status" | "asset_update" (system_update channel)
      | "regime_changed" | "grid_triggered" | "regime_cooldown" (strategy_update channel)
      | "task_progress" (task_progress_update channel),
  "channel": "order_update" | "trade_update" | "position_update" | "asset_update"
      | "quote_update" | "strategy_update" | "system_update" | "task_progress_update",
  "ts": "<ISO 时间>",
  "data": { "...row fields..." }
}
```

`type` → store 分发表:

| type | channel | 调用 |
|---|---|---|
| `ord_cfm` | `order_update` | `holdings.applyOrderPush(enriched, 'update')` + `_notifyOrder()` |
| `trd_cfm` | `trade_update` | `holdings.applyTradePush(enriched)` + ElNotification('成交通知') |
| `pos_push` | `position_update` | `holdings.applyPositionPush(row)`（v118+ broker 推送）|
| `quote` | `quote_update` | `quoteStore.update(...)` + `holdings.applyQuote(row)` |
| `system_status_change` | `system_update` | `systemStore.update(...)`（v117 合并 init_completed）|
| `rpc_status` | `system_update` | `systemStore.setRpcStatus(...)`（RPC 健康监测）|
| `regime_changed` / `grid_triggered` / `regime_cooldown` | `strategy_update` | `strategyStore.applyEvent(...)` |
| `task_progress` | `task_progress_update` | `scriptTaskStore.updateProgress(...)` |
| `ping` / `pong` | （任意）| 心跳处理，不分发 |

### REQ-WS-003: 双向心跳

**协议**: 双向 30s ping/pong (M-005)

- **服务端 → 客户端 ping**: 客户端收到 `{type: 'ping', ts}` 立即回 `{type: 'pong', ts}`（重置服务端 idle timeout）
- **客户端 → 服务端 ping**: 每 30s 主动发 `{type: 'ping', ts: Date.now()}`，累计 3 次（90s）未收到 `pong` 则触发 `force close`，进入重连流程

`quote_update` 走 hqserver 不需要主动 ping（hqserver 自己管心跳）。

`_pongMissed[channel]` 计数:
- 发送 ping 时 +1
- 收到 pong 时清零
- ≥3 时 `socket.close()` → onclose → 重连

### REQ-WS-004: 重连策略（指数退避）

```
delay = min(RECONNECT_BASE_DELAY * 2^(retryCount - 1), RECONNECT_MAX_DELAY)
RECONNECT_BASE_DELAY = 1000ms
RECONNECT_MAX_DELAY = 30000ms
```

- v7 改：从固定 3s 改为指数退避（broker 长时间故障时不会 3s 一次疯狂重连）
- 连接成功 onopen → 重置 `_retryCount[channel] = 0`
- 主动 `disconnect()` → 清 `_retryCount` + 清所有 timer + `socket.onclose = null` 防止重连

退避序列: 1s → 2s → 4s → 8s → 16s → 30s → 30s → ...

### REQ-WS-005: 模块边界与外部 API

**模块边界**:

| 文件 | 职责 | ~行数 |
|---|---|---|
| `client/src/stores/ws_heartbeat.js` | URL/连接/重连/心跳，导出 `createWsManager(onMessage)` 工厂 | 165 |
| `client/src/stores/ws_dispatch.js`  | payload → store 业务分发 + ElNotification | 150 |
| `client/src/stores/ws.js` (facade)  | Pinia store 装配 (`createWsManager(dispatchPayload)`) | ~50 |

**外部 API**（21 view 不变）:

```js
import { useWsStore } from '@/stores/ws'

const wsStore = useWsStore()
wsStore.connect()       // App.vue mount 时调
wsStore.disconnect()    // 登出 + holdings.connect 时调
wsStore.connected       // ref<boolean>
wsStore.lastEvent       // ref<payload>
```

**禁止**: view 直接 import `ws_heartbeat` 或 `ws_dispatch`（保持 facade 单一入口）。

## Scenarios

### S-WS-001: 启动连接 7 个 channel

Given 用户登录成功，App.vue mount
When `wsStore.connect()` 被调用
Then 7 个 channel 各自创建 WebSocket
And 6 个后端 channel URL 含 `?token={jwt}`
And `quote_update` 直连 `{hostname}:8765/`
And 每个连接 onopen 后启动 30s 心跳 (quote_update 除外)

### S-WS-002: 收到 ord_cfm 触发 holdings 更新

Given WS `order_update` 连接稳定
When 服务端推 `{type: "ord_cfm", data: {order_no: "1001", status: "56", stock_code: "600030.SH", ...}}`
Then `lastEvent.value = payload`
And `dispatchPayload(payload)` 路由到 `_onOrderCfm`
And `holdings.applyOrderPush(enriched, 'update')` 被调
And ElNotification 显示「600030.SH 已成交 ...」

### S-WS-003: 客户端心跳超时触发重连

Given `order_update` channel 已连接
When 客户端连续 3 次发送 ping，每次后 30s 未收到 pong
Then `_pongMissed[order_update] = 3`
And `socket.close()` 被调
And 进入 onclose → `_scheduleReconnect` → 1s 后 `_openChannel`

### S-WS-004: 断线指数退避

Given `order_update` 连接断开（broker 故障）
When 连续重连失败 5 次
Then 重连间隔依次: 1s, 2s, 4s, 8s, 16s
And 第 6 次起 `min(30000, ...)` = 30s 上限

### S-WS-005: 主动 disconnect 不重连

Given WS 连接稳定
When 用户登出，`wsStore.disconnect()` 被调
Then 7 个 channel 的 `socket.onclose = null` 防止重连回调
And `socket.close()` 被调
And 所有 timer（reconnect / heartbeat）被清
And `connected.value = false`
And **不**再触发 `_scheduleReconnect`

## Known Issues

- 🟡 7 个 channel 各开一条独立 TCP 连接（未来可考虑多路复用单连接）
- 🟡 `quote_update` 不带 JWT, hqserver 凭 IP/同源信任（生产环境需加 mTLS 或反代鉴权）
- 🟡 `t0_strategy_update` 常量已定义但未注册到 ws_manager（功能悬空）
- 🟢 ~~固定 3s 重连~~ → v7 改指数退避
- 🟢 ~~单向心跳（仅服务端 ping）~~ → v10 改双向（M-005）
