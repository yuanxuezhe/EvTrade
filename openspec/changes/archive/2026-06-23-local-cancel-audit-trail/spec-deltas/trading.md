# trading delta — v9 撤单委托/撤单成交

## MODIFIED Requirements

### REQ-TRADE-003: 撤单（重写）

#### 行为变更
- DELETE 端点**立即 INSERT 一条 cancel-row**（`order_flag=1`），不再仅调 RPC 等待 broker push
- **5 步流程**：pre-checks → INSERT cancel-row → RPC → 分支处理 → WS broadcast
- 响应模型 `CancelResponse` 新增 `cancel_order: Optional[OrderOut]` 字段

#### Pydantic schema 变更
- `OrderOut` 新增 `order_flag: int = 0`
- `TradeOut` 新增 `trade_type: int = 0`
- `CancelResponse` 新增 `cancel_order: Optional[OrderOut] = None`

#### RPC 失败行为
- RPC `ack.code != 0` → cancel-row `status=55`，**不**插 cancel-trade，**不**删行（保留 audit）
- RPC 抛 Exception → 同上 status=55，`status_msg=str(e)`

#### WS broadcast 必做
- 始终推 `order_update`（含 `order_flag: 1`），broker 不会推 cancel-row
- 仅 RPC 成功时推 `trade_update`（含 `trade_type: 1`）

### REQ-TRADE-005: 前端实时性（v9 增 cancel-row）

- WS `order_update` 频道可能携带 `order_flag: 1` 的 cancel-row；前端 `holdings.applyOrderPush` 需短路 `_recomputeStatus`
- WS `trade_update` 频道可能携带 `trade_type: 1` 的 cancel-fill；前端 `holdings.applyTradePush` 透传即可