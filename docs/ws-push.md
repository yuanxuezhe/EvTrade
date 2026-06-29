# WebSocket 推送契约

> 权威源: [server/ws/endpoint.py](../server/ws/endpoint.py) + [server/ws/manager.py](../server/ws/manager.py) + [server/rpc/transport.py:251-295](../server/rpc/transport.py#L251-L295)
> 端点: `ws://<host>:8000/ws/{channel}?token=<JWT>`
> 鉴权: 无 token → close 4001 / token 无效 → close 4001
> 推送方向: **单向 server → client**

## 0. 频道列表

| 频道 | 数据源 | 触发 | 鉴权 |
|---|---|---|---|
| `order_update`   | [server/services/push/ord.py](../server/services/push/ord.py) | broker `ord_cfm` push；本地 `place_order` / `cancel_order` 也手动推 | JWT |
| `trade_update`   | [server/services/push/trd.py](../server/services/push/trd.py) | broker `trd_cfm` push；本地 `cancel_order` 成功时推 cancel-trade | JWT |
| `position_update`| [server/services/push/pos.py](../server/services/push/pos.py) | broker `pos_cfm` push | JWT |
| `asset_update`   | [server/services/push/ast.py](../server/services/push/ast.py) | broker `ast_cfm` push | JWT |
| `quote_update`   | **不走 server** | hqserver :8765 直连 | — |

> 行情频道 `quote_update` 虽然在 [WSManager](../server/ws/manager.py) 的 active_connections 里注册，**但 server 不主动推送**——前端应直连 `ws://<host>:8765` 的 hqserver 拿实时行情。server 端该频道的 heartbeat sender 也会跳过（[server/ws/endpoint.py:50-53](../server/ws/endpoint.py#L50-L53)）。

---

## 1. 订阅协议

### 1.1 建立连接

```
ws://localhost:8000/ws/order_update?token=<JWT>
```

- 鉴权失败 → server `close(code=4001, reason="Unauthorized")`
- 鉴权成功 → `accept()` + 加入 channel 集合

### 1.2 双向心跳（v10 增）

**服务端主动 ping**（[server/ws/endpoint.py:45-66](../server/ws/endpoint.py#L45-L66)）:
- 启动后每 `WS_HEARTBEAT_INTERVAL = 30s` 发送 `{"type":"ping","ts":<float>}`
- 累计 `WS_CLIENT_TIMEOUT = 60s` 没收到任何 client 消息 → `close(code=4408, reason="heartbeat timeout")`
- `quote_update` 频道**不启动**心跳（直连 hqserver）

**客户端主动 ping**:
- 客户端发送 `{"type":"ping","ts":<float>}`
- 服务端立即回复 `{"type":"pong","ts":<相同 ts>}`
- 同时刷新 `last_recv` 时间戳（任何收到的消息都刷新，包括非 ping）

**客户端发 pong / 业务消息**:
- 服务端只刷新 `last_recv`，**不做业务处理**（推送是单向 server→client）

### 1.3 关闭码

| Code | 含义 |
|---|---|
| 4001 | Unauthorized（无/无效 token） |
| 4408 | heartbeat timeout（60s 内无消息） |
| 1000 | 客户端正常断开 |

---

## 2. 推送 Payload 格式

权威源: [server/rpc/transport.py:251-274](../server/rpc/transport.py#L251-L274) 构造 / [server/ws/manager.py:33-48](../server/ws/manager.py#L33-L48) 广播

**通用 envelope**（所有 4 频道一致）:

```json
{
  "type": "ord_cfm | trd_cfm | pos_cfm | ast_cfm",
  "channel": "order_update | trade_update | position_update | asset_update",
  "ts": "2026-06-29 14:35:22.123",
  "data": { /* 见 §3-§6 */ }
}
```

> v8 起 `data` 注入 `trd_date`（权威源 = 当前激活交易日），覆盖 broker 推回来的 trd_date（broker 可能为空 / 格式不规范）。前端 holdings 缓存用此做激活日守门：[server/rpc/transport.py:256-264](../server/rpc/transport.py#L256-L264)
>
> v10 起 `ts` 统一为 `"YYYY-MM-DD HH:MM:SS.fff"`（`format_ts(tz='local')`）

---

## 3. `order_update` 频道 payload

`data` 字段（broker `ord_cfm` 行 + `trd_date` 注入）:

| 字段 | 类型 | 来源 | 说明 |
|---|---|---|---|
| `trd_date` | str | **server 注入** | YYYYMMDD（激活交易日） |
| `order_id` | str | broker | 柜台委托号 |
| `stock_code` | str | broker | |
| `order_status` | str | broker | 48/49/50/51/52/53/55 |
| `order_volume` | int | broker | broker 改单后真实数（v10） |
| `traded_volume` | int | broker | |
| `price` | float | broker | |
| `traded_price` | float | broker | |
| `strategy_name` | str | broker | |
| `remark` | str | broker | **= 本地 `order_no`（关键匹配键）** |
| `order_time` | str | broker | 紧凑格式 → server 标准化 |

**本地手动触发**（`POST /api/orders/place` 成功时，[server/api/orders/place.py:121-137](../server/api/orders/place.py#L121-L137)）:
```json
{
  "trd_date": "...",
  "order_no": "...",
  "remark": "...",
  "order_id": "...",
  "stock_code": "...",
  "status": "49",
  "status_msg": "已报",
  "volume": ...,
  "traded_volume": 0
}
```

**本地手动触发**（`DELETE /api/orders/{order_no}` 始终推，[server/api/orders/cancel.py:150-176](../server/api/orders/cancel.py#L150-L176)）— 撤单行带 `order_flag=1, user_def="CANCEL:<orig_order_no>"`:
```json
{
  "trd_date": "...",
  "order_no": "...",
  "remark": "...",
  "order_id": "",
  "stock_code": "...",
  "status": "53|55",
  "status_msg": "已撤 | <失败原因>",
  "volume": 0,
  "traded_volume": 0,
  "order_flag": 1,
  "user_def": "CANCEL:..."
}
```

---

## 4. `trade_update` 频道 payload

`data` 字段（broker `trd_cfm` 行 + `trd_date` 注入）:

| 字段 | 类型 | 来源 | 说明 |
|---|---|---|---|
| `trd_date` | str | **server 注入** | |
| `traded_id` | str | broker | 成交编号 |
| `stock_code` | str | broker | |
| `traded_volume` | int | broker | |
| `traded_price` | float | broker | |
| `account_id` | str | broker | v10 透传 |
| `strategy_name` | str | broker | v10 透传 |
| `remark` | str | broker | **= 本地 `order_no`** |

> broker `trd_cfm` 缺少 `traded_amount` / `traded_time` — server 在 [server/services/push/trd.py:62-77](../server/services/push/trd.py#L62-L77) 持久化时计算 `amount = price * volume`，`trade_time` 用 push 包的 `ts`

**本地手动触发**（撤单成功的 cancel-trade，[server/api/orders/cancel.py:164-176](../server/api/orders/cancel.py#L164-L176)）:
```json
{
  "trd_date": "...",
  "trade_id": "CANCEL-<cancel_order_no>-<unix_ts>",
  "order_no": "<cancel_order_no>",
  "stock_code": "...",
  "order_type": "23|24",
  "price": ...,
  "volume": <剩余可撤量>,
  "amount": <price * volume>,
  "trade_time": "...",
  "trade_type": 1
}
```

> `trade_type=1` 是 v9+ 标记，区别于正常成交（`trade_type=0`）

---

## 5. `position_update` 频道 payload

`data` 字段（broker `pos_cfm` 行 + `trd_date` 注入）:

| 字段 | 类型 | 来源 | 说明 |
|---|---|---|---|
| `trd_date` | str | **server 注入** | |
| `stock_code` | str | broker | |
| `last_vol` | int | broker | 期初 |
| `volume` | int | broker | 总持仓（broker 可能不送，server 兜底用 `avl_amt`） |
| `avl_amt` | int | broker | 可用数量（**v10 原字段名**，不再 alias 为 `available`） |
| `avg_price` | float | broker | 成本价（**v10 原字段名**，不再 alias 为 `cost`） |
| `market_value` | float | broker | 持仓市值（**仅作参考**，前端用 quote store 实时算） |

> 持久化后端**不存** `market_value`（Position ORM 无此列），由前端根据行情实时重算
> 权威源: [server/services/push/pos.py:23-56](../server/services/push/pos.py#L23-L56)

---

## 6. `asset_update` 频道 payload

`data` 字段（broker `ast_cfm` 行 + `trd_date` 注入）:

| 字段 | 类型 | 来源 | 说明 |
|---|---|---|---|
| `trd_date` | str | **server 注入** | |
| `account_id` | str | broker | 账号（v10 透传） |
| `total_asset` | float | broker | 总资产 |
| `cash` | float | broker | 现金 |
| `frozen_cash` | float | broker | 冻结资金（**v10 原字段名**，不再 alias 为 `frozen`） |
| `market_value` | float | broker | 持仓市值 |

> 权威源: [server/services/push/ast.py:14-34](../server/services/push/ast.py#L14-L34)

---

## 7. push 路由表

| broker push func | server WS 频道 | 路由位置 |
|---|---|---|
| `ord_cfm` | `order_update`   | [server/rpc/transport.py:47](../server/rpc/transport.py#L47) |
| `trd_cfm` | `trade_update`   | [server/rpc/transport.py:48](../server/rpc/transport.py#L48) |
| `pos_cfm` | `position_update`| [server/rpc/transport.py:49](../server/rpc/transport.py#L49) |
| `ast_cfm` | `asset_update`   | [server/rpc/transport.py:50](../server/rpc/transport.py#L50) |
| `ord_err` | (无 WS 频道，仅日志) | unknown func → warn |
| `cxl_err` | (无 WS 频道，仅日志) | unknown func → warn |
| `ord_ack` | (无 WS 频道，仅日志) | unknown func → warn |
| `acc_sts` | (无 WS 频道，仅日志) | unknown func → warn |

> 其他推送类型被 server 忽略：[server/rpc/transport.py:251-254](../server/rpc/transport.py#L251-L254) `"RPClient.push ignore unknown func=%r"`

---

## 8. 前端订阅样例（JavaScript）

```js
// 建立连接
const ws = new WebSocket(
  `ws://${host}:8000/ws/order_update?token=${jwt}`
);

ws.onopen = () => console.log('connected');
ws.onmessage = (e) => {
  const msg = JSON.parse(e.data);
  if (msg.type === 'ping') return;       // 服务端主动 ping
  if (msg.channel === 'order_update') {
    const { data, ts } = msg;
    // data.trd_date 由 server 注入，可用于激活日守门
    if (data.trd_date !== activeTradingDay) return;  // 守门
    store.applyOrderPush(data);
  }
};
ws.onclose = (e) => {
  if (e.code === 4001) router.push('/login');
  if (e.code === 4408) console.warn('heartbeat timeout');
};

// 客户端主动 ping（保活）
setInterval(() => {
  if (ws.readyState === 1) ws.send(JSON.stringify({ type: 'ping', ts: Date.now() }));
}, 25000);
```

---

## 9. 与 OpenSpec 的关系

- 推送频道列表属于 OpenSpec `push` capability 的**实现细节**
- 完整推送状态机（order status 推断、cancel-row 本地代理、trd_date 守门）参见 [openspec/specs/push/spec.md](../openspec/specs/push/spec.md)
- 本文档是**字段级契约**，spec 是**能力级契约**——并行存在
