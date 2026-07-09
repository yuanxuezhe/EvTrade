# Spec Delta: backend-ws

## ADDED Requirements

### REQ-WS-100: ws subscribe 协议（2026-07-09 增量）

`/ws/quote_update` channel 支持前端按标的订阅。

#### Scenario: 客户端发起 subscribe

- **WHEN** 客户端发 `{type:"subscribe", stock_codes:["600519.SH","000001.SZ"]}`
- **THEN** 后端:
  1. 在 `WSManager.subscriptions[ws]` 加 2 个 stock_code
  2. 在 `WSManager.subscribers[stock_code]` 加此 ws
  3. 同步查 `repo.quote_snapshots.get_latest_multi(db, stock_codes)`
  4. 对每个有快照的标的推 `{type:"snapshot", stock_code:"...", data:{...23 字段 + ts}}`
  5. 推 `{type:"subscribe_ack", stock_codes:[...], count:N}`（N=订阅的数量）
- **AND** 快照缺失的标的（如新代码 broker 还未推）跳过 snapshot 帧，但 subscribe_ack 仍然收到

#### Scenario: 客户端发起 unsubscribe

- **WHEN** 客户端发 `{type:"unsubscribe", stock_codes:["..."]}`
- **THEN** 后端从两边 registry 移除这些 stock_code
- **AND** 此 ws 此后不收这些标的的 tick

#### Scenario: tick 进,仅推给订阅者

- **WHEN** QuoteConsumer._fanout_tick(...)
- **AND** `data.stock_code` in `WSManager.subscribers[...]` 中存在订阅者集合
- **THEN** `ws_manager.broadcast_to_subscribers(stock_code, payload)`：只发该集合内的 ws
- **AND** `subscribers[stock_code]` 为空 → 不推送（0 流量）

#### Scenario: ws disconnect

- **WHEN** 任一 ws 异常关闭（heartbeat timeout / 客户端断网）
- **THEN** `WSManager.cleanup_ws(ws)`：从所有 `subscribers[stock_code]` 移除此 ws,从 `subscriptions[ws]` 整体删除

### MODIFIED Requirements

#### Requirement: WSManager 数据结构

`WSManager.__init__` 增补:

- `subscriptions: Dict[WebSocket, Set[str]]` — 每个 ws 订阅的 stock_code 集合
- `subscribers: Dict[str, Set[WebSocket]]` — 每个 stock_code 订阅此的 ws 集合（倒排）

`WSManager` 类新增方法:

- `add_subscription(ws, stock_code: str)`
- `remove_subscription(ws, stock_code: str)`
- `broadcast_to_subscribers(stock_code: str, message: dict, ...)`
- `cleanup_ws(ws)` — disconnect 时整体回收

`WSManager.broadcast(channel, message, ...)` 行为不变（其它 channel 如 order_update/trade_update 仍按 channel broadcast）

### REQ-WS-200: ws 兼容老前端

未发送 subscribe 消息的 ws（依然存在 ≤30s 兼容期）走 broadcast 模式，老 ws_dispatch._onQuote 路径继续可用。

#### Scenario: 老前端无 subscribe 仍能收 quote

- **WHEN** ws 连接 `/ws/quote_update`，未发任何 subscribe
- **AND** QuoteConsumer 收到 tick
- **THEN** 触发 `WSManager.broadcast("quote_update", payload)`（fallback：未订阅的 ws 也广播）
- **AND** 新协议下走 `broadcast_to_subscribers` 仅推给订阅者;但 fallback 仍 broadcast 给所有，保留向后兼容
