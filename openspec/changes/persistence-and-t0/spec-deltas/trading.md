# Spec Delta — persistence-and-t0 → trading

## MODIFIED Requirements

### REQ-TRADE-001（兼容保留）

委托查询：`GET /api/orders?stock_code=&status=&trading_day=`

- `trading_day` 参数**可选**，缺省按 `resolve_default_trd_date()` 决定
- 返回 `{code: 0, msg: "", list: [...]}`
- 全部从 `orders` 表 SELECT，**不调 RPC**

### REQ-TRADE-002（重写）

下单：`POST /api/orders/place`

- 屏障：`require_trading_day` + `require_trading_session` + `require_trader`
- 请求体：`{client_order_id, stock_code, order_type, price_type, price, volume}`
- 流程：
  1. 幂等：`client_order_id` 已存在 → 200 + 原单
  2. 调 `services/order_no.next()` 生成 8 位 `order_no`
  3. INSERT `orders` (status="48"待报, TRD_DATE=current, ORDER_RMRK=order_no, order_id=占位)
  4. 调 `ord_stk(..., remark=order_no)`
  5. 成功 → UPDATE order_id + status="49"已报
  6. 失败 → UPDATE status="55"废单 + status_msg=err
  7. 推 WS `order_update`

### REQ-TRADE-003（重写）

撤单：`DELETE /api/orders/{order_id}`

- 屏障：同上
- 流程：
  1. SELECT orders → 404 if 不存在
  2. 调 `rpc_cancel_order(order_id)`
  3. 成功 → **不本地改 status**（等 push 推 53已撤）
  4. 失败 → 500 + 错误信息

## ADDED Requirements

### REQ-TRADE-006: 查询走本地 DB

- 4 个查询端点（orders/trades/positions/asset）全部从本地表 SELECT
- 支持 `?trading_day=YYYYMMDD` 覆盖默认
- 默认值 = `resolve_default_trd_date()`：
  - 已激活交易日 → 用 `current_date`
  - 未激活 → 取 `MAX(TRD_DATE)` 兜底
  - 表空 → 今日 `'YYYYMMDD'`

### REQ-TRADE-007: 订单序号生成器

- 8 位数字字符串 `'10000001'`-`'99999999'`
- DB 表 `order_no_seq`（单行，CHECK id=1）
- 原子自增：SQLite UPSERT + RETURNING
- 并发安全（pytest 并发测试）
- 持久化（重启不重置）

### REQ-TRADE-008: 废单处理

- RPC `ord_stk` 失败 / 柜台返回 code != 0：
  - 本地 orders.status = "55"废单
  - status_msg = 错误信息
  - 推 WS `order_update`（前端红条）
  - **不** raise HTTPException（200 OK + 状态字段告知）

### REQ-T0-001: 配平计算

- `POST /api/t0/calculate`
- 输入：`{cost_price, base_volume, sell_volume, sell_price, buy_price?, buy_volume?, fee_config}`
- 输出：`{break_even_buy_price, break_even_buy_volume, projected_pnl, hedged_pnl, summary}`
- 费率：`commission`（默认万一 0.0001） + `stamp_tax`（卖出千 1 0.001） + `slippage`（0.001）

### REQ-T0-002: 一键下单

- `POST /api/t0/execute`
- 输入：`{stock_code, action: "sell"|"buy_back", volume, price_type=14}`
- 自动从 `quote_snapshots` 拿对手价
- 走 `place_order` 同路径

### REQ-FEE-001: 费率配置

- `GET /api/settings/fee` 返回当前费率
- `PATCH /api/settings/fee` 改费率（需要 trader 角色）
- 存 `fee_config` 表（单行）
- 默认值：`commission=0.0001`、`stamp_tax=0.001`、`slippage=0.001`
