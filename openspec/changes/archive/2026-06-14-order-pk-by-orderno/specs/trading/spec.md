## MODIFIED Requirements

### Requirement: 委托主表主键为 `(trd_date, order_no)`

委托主表复合主键 SHALL 为 `(trd_date, order_no)`,其中 `order_no` 是本地 8 位原子序号;`order_id` 字段 SHALL 为可空列,由 ord_cfm 推送到达时写入。

下单时 MUST 不预占 `order_id`(无 `PENDING-*` 占位字符串),broker ack / ord_cfm 到达前 `order_id` 为空。

#### Scenario: 下单后 broker 未回报前 order_id 为空
- **WHEN** trader `POST /api/orders/place` 成功,RPC ack 未带回 `order_id`
- **THEN** 响应 `OrderOut.order_id = ""`
- **AND** DB 行 `orders.order_id IS NULL`
- **AND** DB 行 `orders.status = "48"`(待报),等 ord_cfm 推断

#### Scenario: broker ack 带回 order_id 时写入
- **WHEN** trader `POST /api/orders/place` 成功,RPC ack 带回 `order_id = "916460217"`
- **THEN** DB 行 `orders.order_id = "916460217"`
- **AND** DB 行 `orders.status = "49"`(已报,本地推断:累计=0 + broker 未推撤单类 status)
- **AND** 响应 `OrderOut.order_id = "916460217"`

#### Scenario: broker ack 失败 status 设为废单
- **WHEN** trader `POST /api/orders/place`,broker ack `code != 0`
- **THEN** DB 行 `orders.status = "55"`(废单)
- **AND** `OrderOut.status_msg` 含 broker 返回的错误信息

### Requirement: 撤单 endpoint URL 参数为 `order_no`

撤单 endpoint `DELETE /api/orders/{order_no}` SHALL 通过 `order_no` 定位本地 Order(主键 `(trd_date, order_no)`),内部用查到的 `order.order_id` 调 `cancel_ord` RPC;broker `order_id` 尚未到达时 SHALL 返回 409 `BROKER_NOT_READY`。

#### Scenario: 正常撤单
- **WHEN** trader `DELETE /api/orders/10000001?trd_date=20260616`,DB 中 Order 存在且 `order_id` 已填
- **THEN** 后端用 `order.order_id` 调 `cancel_ord` RPC
- **AND** 响应 `CancelResponse.code = 0`

#### Scenario: broker order_id 尚未到达时撤单
- **WHEN** trader `DELETE /api/orders/10000001?trd_date=20260616`,DB 中 Order 存在但 `order_id IS NULL`(broker 尚未回报)
- **THEN** 后端 MUST NOT 调 RPC
- **AND** 返回 HTTP 409,`detail.code = "BROKER_NOT_READY"`

#### Scenario: 撤单 endpoint 不再接受 broker order_id
- **WHEN** trader `DELETE /api/orders/916460217`(broker order_id)
- **THEN** 后端查 `Order.order_no = "916460217"` 找不到对应单
- **AND** 返回 HTTP 404,`detail.code = "NOT_FOUND"`
- **NOTE**: 前端 MUST 改用 `order_no` 调用

### Requirement: OrderOut.order_id 允许空串

`OrderOut.order_id` SHALL 默认空字符串 `""`,代表 broker `order_id` 尚未到达(下单后到 ord_cfm 到达前的窗口期)。前端 MUST 接受空串语义,不再期望 `PENDING-*` 前缀。

#### Scenario: 响应里 order_id 为空串
- **WHEN** trader 调 `place` 后立即 `GET /api/orders?trd_date=...`
- **THEN** 响应中 `list[*].order_id = ""`(broker 还没回报)
- **AND** 前端 MUST 不报错,空串代表"等待 broker 回报中"

#### Scenario: 响应里 order_id 已填
- **WHEN** broker ord_cfm 推送到达后 `GET /api/orders?trd_date=...`
- **THEN** 响应中 `list[*].order_id = "<broker_order_id>"`
