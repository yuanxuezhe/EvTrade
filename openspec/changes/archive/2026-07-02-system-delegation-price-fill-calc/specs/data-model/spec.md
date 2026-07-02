## MODIFIED Requirements

### Requirement: 委托的 `cancelled_volume` 字段写入语义

The system MUST 维持 `orders.cancelled_volume` 与本地"撤单 / 拒单 / broker 推回"四类写入路径的语义统一：

- **trd_cfm 路径不写** `cancelled_volume`
- **本地 DELETE 端点成功**（broker `ack.code == 0`）：原委托 `cancelled_volume = volume`（全撤语义，立即生效）
- **本地下单被柜台拒单**（broker `ack.code != 0` → `status = "55"`）：`cancelled_volume = volume`
- **broker ord_cfm 推回拒单类 status 且本次未推 cancelled_volume 字段**：`cancelled_volume = volume`（兜底）
- **broker ord_cfm 携带 cancelled_volume / cancel_volume / withdrawn_volume 任一字段名**：累加 + 截断至 `≤ volume`（既有 v8 行为保留）
- **本地 DELETE 端点失败**（broker `ack.code != 0`）：原委托 `cancelled_volume` 不动（仅 cancel-row 自身写 `status = "55"`）

#### Scenario: 本地撤单成功时抹平

- **WHEN** `DELETE /api/orders/{order_no}` 收到 broker ack.code == 0
- **THEN** 原委托 `cancelled_volume = volume`，不等待 broker 后续 ord_cfm 兜底

#### Scenario: 本地拒单时抹平

- **WHEN** `POST /api/orders/place` 收到 broker ack.code != 0
- **THEN** 当前委托 `status = "55"`，`cancelled_volume = volume`

#### Scenario: broker 推回废单类 status 的兜底

- **WHEN** `push/ord.py` 收到的 broker ord_cfm `order_status` 落在拒单类且本次未推 cancelled_volume 字段
- **THEN** `cancelled_volume = volume`（与本地下单拒单等价语义）

#### Scenario: broker 推回 cancelled_volume 字段时累加

- **WHEN** `push/ord.py` 收到的 broker ord_cfm 携带 cancelled_volume / cancel_volume / withdrawn_volume 任一字段名
- **THEN** `cancelled_volume += broker_value`，截断至 `≤ volume`

#### Scenario: DELETE 端点失败保持原委托不变

- **WHEN** `DELETE /api/orders/{order_no}` 收到 broker ack.code != 0
- **THEN** 原委托 cancelled_volume 不动；仅 cancel-row 自身 `status = "55"`

### Requirement: 成交表的 `amount` 字段本地算口径

The system MUST 在 `push/trd.py::handle_trd_cfm` 中**本地**计算 `trades.amount = price × volume`，即使 broker 推送了 `traded_amount` 字段也 MUST NOT 采纳。

#### Scenario: trd_cfm 落表

- **WHEN** `push/trd.py` 处理一行 broker trd_cfm（携带 price / volume / traded_amount 字段）
- **THEN** `Trade(...)` 实例的 `amount` 属性 = `trade.price * trade.volume`，broker.traded_amount 不入表

#### Scenario: broker 推怪异 traded_amount

- **WHEN** broker trd_cfm 行的 `traded_amount` 字段值与 `price × volume` 不一致（如含费用 / 精度差异）
- **THEN** DB 中 `trades.amount` 仍等于 `price × volume`，broker 字段被丢弃
