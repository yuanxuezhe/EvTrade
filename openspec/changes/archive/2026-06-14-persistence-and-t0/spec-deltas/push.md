# Spec Delta — persistence-and-t0 → push

## MODIFIED Requirements

### REQ-PUSH-001（兼容保留）

监听 `EvTrade.Test.Push` 队列，把柜台主动推送转成两路：
- **路 1（落库）**：写/更新本地 SQLite
- **路 2（推 WS）**：广播到 WebSocket 频道

## ADDED Requirements

### REQ-PUSH-005: ord_cfm 写 orders

- 收到 `ord_cfm` push 包
- 匹配键：**先 `order_id`，兜底 `order_remark`（= ORDER_NO）**
- 命中：UPDATE 订单状态、traded_volume、traded_amount、status_msg、avg_price
- 未命中：INSERT 新行（其他终端下的单）
- 推 WS `order_update`

### REQ-PUSH-006: trd_cfm 写 trades + 更新 orders

- 收到 `trd_cfm` push 包
- 步骤 1：UPSERT `trades` (按 trade_id)
- 步骤 2：SELECT orders WHERE order_id=row.order_id
- 步骤 3：UPDATE orders.traded_volume += row.volume, traded_amount += row.amount, avg_price = traded_amount/traded_volume
- 推 WS `trade_update` + `order_update`

### REQ-PUSH-007: pos_cfm 写 positions（**新增**）

- 收到 `pos_cfm` push 包
- UPSERT `positions` (按 stock_code)
- 推 WS `position_update`

### REQ-PUSH-008: ast_cfm 写 assets（**新增**）

- 收到 `ast_cfm` push 包
- UPDATE `assets` (id=1 单行)
- 推 WS `asset_update`

## Channels 映射

```python
_PUSH_CHANNEL = {
    "ord_cfm": "order_update",
    "trd_cfm": "trade_update",
    "pos_cfm": "position_update",
    "ast_cfm": "asset_update",
}
```
