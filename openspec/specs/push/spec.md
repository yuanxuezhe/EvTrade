# push — 柜台主动推送 → WebSocket 路由

## Purpose

QMT 柜台通过 RabbitMQ 主动推送（`EvTrade.Test.Push` 队列）异步通知状态变化。
后端 RPC 客户端必须把这些 push 消息按事件类型路由到对应的 WebSocket 频道。

## Requirements

### REQ-PUSH-001: 监听 Push 队列

- RPC 客户端 `start()` 时启动 push listener
- 队列名：`EVTRADE_QUEUE_PUSH`（默认 `EvTrade.Test.Push`）
- 收到消息后根据 `func` 字段判断事件类型

### REQ-PUSH-002: 事件路由

| Func 字段 | 事件 | 路由到 WS 频道 | 前端处理 |
|---|---|---|---|
| `ord_cfm` | 委托状态变更/成交 | `order_update` | 替换 store 中同 order_id 的项 |
| `trd_cfm` | 成交回报 | `trade_update` | 追加到 trades 列表 |
| `qry_pos` 等查询响应 | ❌ **不应在 push 出现** | — | 忽略，**应被 reply 队列消费** |

### REQ-PUSH-003: WS 频道 → 前端 store

- `order_update` → `client/src/stores/order.js` 替换 orders 中同 order_id
- `trade_update` → 追加到 trades
- `position_update` → 重拉（push 当前未路由）
- `asset_update` → 重拉（push 当前未路由）

### REQ-PUSH-004: 健壮性

- 解析失败的 push 消息打 warning 日志，不影响后续消息
- 未知 `func` 字段 → 忽略 + warning 日志
- WS 客户端断开时 push listener 不受影响

## Scenarios

### S-PUSH-001: 成交回报

Given 委托 12345 部分成交 100 股 @ 12.34  
When 柜台 push `trd_cfm` 消息  
Then 后端解析后 push 到 WS 频道 `trade_update`  
And 前端 `trades` store 追加 `{trade_id, order_id, stock_code, volume:100, price:12.34, ...}`

### S-PUSH-002: 委托状态变更

Given 委托 12345 从"已报"变"部成"  
When 柜台 push `ord_cfm`  
Then WS 频道 `order_update` 推 `{order_id:"12345", status:"51", traded_volume:50, ...}`  
And 前端 store 替换 orders 中同 id 的项

### S-PUSH-003: Push 误路由到 qry_pos

⚠️ **已知问题**：QMT 端有时把 ord_cfm 路由到 `qry_pos` 队列名  
Then 解析时只有 `{code, msg}` 字段，没有 stock_code/evt_type  
Action: 打 warning 日志，**不重派**（避免循环）

## Push 消息结构

```
func=ord_cfm
RS1: [{code: 0, msg: ""}]
RS2: [{
    order_id: "...",
    stock_code: "...",
    order_type: "23"|"24",
    volume: ...,
    price: ...,
    price_type: ...,
    status: "48"-"57"|"255",
    traded_volume: ...,
    traded_price: ...,
    order_time: "HH:MM:SS",
    order_remark: "...",
    status_msg: "..."
}]
```

## Known Issues (from analysis)

- 🟡 `position_update` 和 `asset_update` 频道路由待完善
- 🟡 `func=qry_pos` 误路由问题根因是 QMT 端，不在本项目修复范围但需健壮处理
- 🟡 push handler `handle_pos_cfm` 不写 `market_value`（Position ORM 无此列，前端实时计算）
- 🟢 push listener 的解析器 `_parse_ord_cfm` 散落在 `client.py`，应统一为 `rpc-protocol` 能力
