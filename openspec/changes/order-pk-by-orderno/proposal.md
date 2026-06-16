## Why

`orders` 表当前主键是 `(trd_date, order_id)`,但 broker 真实 `order_id` 在下单时不可知,代码用 `PENDING-{order_no}` 占位 + 删-插交换 (`server/api/orders.py:144` / `L191-213`) 强行绕过,出现 PENDING 漏更新 / 交易落库无法累计等 bug(commit 8414425 即是修这类问题)。同时 `Order.status` 直接抄 broker 推的字段,无法应对 broker 漏推 / 推错,客户端边界态(部成部撤)展示完全依赖 broker 正确性。

将主键改为本地 8 位原子序号 `order_no`,`order_id` 改成可空,broker 推送到达时再写入;同时把委托 status 改为本地按"累计成交 + 撤单信号"推断,消除 PENDING- 占位 hack 和对 broker 推 status 准确性的依赖。

## What Changes

- **PK 改造** — `orders` 复合主键从 `(trd_date, order_id)` 改为 `(trd_date, order_no)`;`order_id` 变成可空列,由 ord_cfm 推送写入
- **删除 PENDING- 占位 + 删-插交换** — `place_order` 直接 INSERT 不带 `order_id`;broker ack 返回时单条 UPDATE 写入 `order_id`(若带回);不再有 "PENDING-XXX" 字符串出现在 DB / 响应
- **trd_cfm 用 `remark` 匹配 Order** — 不再按 `broker_order_id` 查,按 broker 透传的 `remark` (= `order_no`) 查;不再依赖 ord_cfm 先到
- **Order.status 本地推断** — 新增 `_infer_order_status(order, broker_status=None)`,每次推送(ord_cfm / trd_cfm)处理时根据累计成交 vs 委托总量 + broker 推的撤单信号(52/53/54)推断 49/50/51/53/56;`status` 字段语义统一为"本地推断的委托状态"
- **终态保持** — status 进入终态(51/52/53/54/55/56)后不再被后续 trd_cfm 累计推断覆盖,避免撤单后被覆盖回 50
- **撤单路由改用 `order_no`** — `DELETE /api/orders/{order_no}`(原 `/{order_id}`);查 Order by `(trd_date, order_no)`,内部用查到的 `order.order_id` 调 RPC;`order_id` 尚未到达时返回 409 `BROKER_NOT_READY`
- **API 响应** — `OrderOut.order_id` 改为 `str = ""`(broker 未回报前为空串,前端据此判断),不再出现 `PENDING-` 前缀
- **DB 迁移** — 无 Alembic;dev 期 `rm server/evtrade.db` 重建,生产需手工迁移或新装

**BREAKING**:
- 撤单 endpoint URL 变更:`DELETE /api/orders/{order_id}` → `DELETE /api/orders/{order_no}`
- `OrderOut.order_id` 在 broker 未回报前由 `PENDING-{order_no}` 变更为空字符串 `""`
- `orders` 表 schema 不兼容,需重建数据库

## Capabilities

### New Capabilities
(无)

### Modified Capabilities
- `trading`: 委托主表主键变更;`POST /api/orders/place` 响应 `order_id` 字段语义变更;`DELETE /api/orders/{...}` URL 参数从 `order_id` 改为 `order_no`;`OrderOut.order_id` 允许为空串
- `push`: `ord_cfm` handler 简化为只写 `order_id`(不再做 PENDING→real 转换);`trd_cfm` handler 改用 `remark` 匹配 Order;新增 `_infer_order_status` 状态本地推断逻辑

## Impact

- **Schema**: `server/models/orm.py` Order 表(L27-56)— 主键 + 约束 + 索引
- **API**: `server/api/orders.py` — `place_order`(L99-250) + `cancel_order`(L255-287)
- **Services**: `server/services/push_handlers.py` — `handle_ord_cfm` + `handle_trd_cfm` + 新增 `_infer_order_status` / `_status_msg`
- **Tests**: `server/test_models.py`、`server/test_orders_api.py`、`server/test_push_handlers.py`
- **DB**: `server/evtrade.db` 需删除重建
- **Broker 协议**: trd_cfm 推送需带 `remark` 字段(= 下单时送的 `order_no`),同 ord_cfm。如 broker 实际未送,需要 broker 端协调
- **前端**: 调用撤单需从 `order_id` 改为 `order_no`;`order_id` 字段空串语义需前端接受
