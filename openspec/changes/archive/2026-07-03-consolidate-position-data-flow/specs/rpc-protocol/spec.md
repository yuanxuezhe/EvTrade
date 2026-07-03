## MODIFIED Requirements

### Requirement: REQ-RPC-004.1 业务字段映射表与 parsers 职责

`qry_pos` / `qry_ord` / `qry_mch` / `qry_ast` 等业务函数的 broker 字段 → server 内部命名的映射表 MUST 按下表。变更重点:`qry_pos` 的 server 内部命名列 = parser 输出 dict 键名 = DB 列名,三者完全一致;brokers wire 字段名 MUST 仅在 parser 内部读取,不在 parser 输出侧出现。`qry_ast` 在变更前后无差异 (Asset broker 字段名已与 DB 列名一致)。

#### Scenario: qry_pos parser 输出与 Position ORM 列名一致 (变更后)

- **WHEN** broker 返回 RS2 持仓行 `{stock_code, last_vol, volume, avl_amt, avg_price, market_value}`
- **THEN** `_parse_positions` 输出 dict 键为 `{stock_code, last_vol, vol, avl_vol, cost_price}` (market_value 在 parser 丢弃)
- **AND** reconcile.py 直接 `Position(... vol=p['vol'] ...)` 无 remap 块
- **AND** broker 原字段名 `volume` / `avl_amt` / `avg_price` 在 parser 输出 dict 中不再出现

#### Scenario: parsers 职责单一 (变更后)

- parsers 层职责:在 parser 输出 dict 这一个边界完成 broker wire → server 内部命名的重命名;输出 dict 键名 = server 全栈 (reconcile / API / ORM / 前端 store) 使用的字段名
- API 层 / ORM 层 / 前端 store:直接读 parser 输出字段名,**不再做任何 broker→server 字段重命名**

| RPC func | broker 字段 (xtquant 协议) | server 内部命名 (parser 输出 = DB 列名) |
|---|---|---|
| `qry_pos` | `stock_code, last_vol, volume, avl_amt, avg_price, market_value` | `stock_code, last_vol, vol, avl_vol, cost_price` (market_value 在 parser 丢弃) |
| `qry_ord` | `order_id, stock_code, order_type, price_type, price, order_volume, traded_volume, traded_price, order_status, status_msg, strategy_name, order_remark, order_time` | `order_id, stock_code, order_type, price_type, price, volume, traded_volume, traded_price, status, status_msg, strategy_name, order_remark, order_time` |
| `qry_ast` | `account_id, cash, frozen_cash, market_value, total_asset` | `cash, frozen_cash, market_value, total_asset` (`account_id` 不存储) |
| `qry_mch` | `order_id, traded_id, stock_code, order_type, traded_volume, traded_price, traded_amount, strategy_name, order_remark, traded_time` | `order_id, trade_id, stock_code, order_type, volume, price, amount, strategy_name, order_remark, trade_time` |
| `cancel_ord` / `ord_stk` | `seq, order_id, result` | 透传 |

字段名权威源:`iquant/xtquant_api.py` 第 130-200 行 (query handler) 和 280-340 行 (push callback)。

### Requirement: REQ-RPC-004.1.1 broker status 字段重映射 (v11 段,文字保留不变)

`qry_ord` 响应 `order_status` 字段值 MUST 直接写入 `Order.status`,无翻译层。`push_handler_ord` 收到 broker 推 `order_status` 字段 MUST 直接采用,不调用任何翻译函数。字段名唯一权威:broker 原字段名 (`order_status`),不再 alias `status`。

#### Scenario: qry_ord 响应 status 直接采用 broker 码 (v11)

- **WHEN** `qry_ord` 响应 RS2 含 `order_status='54'` (broker CANCELED)
- **THEN** API 层 Pydantic 序列化时映射为 `status='54'`
- **AND** 前端 view 按 broker 字典解读: `STATUS_LABEL['54']` = '已撤'
- **AND** 跨系统对账时无需翻译

#### Scenario: push handler 直接采用 broker order_status (v11)

- **WHEN** broker 推 ord_cfm `order_status='57'` (broker JUNK)
- **THEN** `handle_ord_cfm` 直接采用 `Order.status='57'`,不调用 `_infer_order_status`
