## MODIFIED Requirements

### Requirement: ord_cfm 推送只填 order_id,不动 status

`handle_ord_cfm` MUST 通过 broker 透传的 `remark` (= 本地 `order_no`) 匹配本地 Order;匹配到后 MUST 将 broker `order_id` 写入 `Order.order_id`,并调用 `_infer_order_status` 推断 `Order.status`(临时接收 broker 推的 `status` 字段作为推断参数);MUST NOT 单独写 `traded_volume` / `traded_amount` / `avg_price` / `status_msg`(累计由 trd_cfm 负责)。

#### Scenario: ord_cfm 首次到达,本地 Order order_id 为空
- **WHEN** broker 推 `ord_cfm {remark: "10000001", order_id: "916460217", status: "49", ...}`
- **THEN** 后端用 `remark` 匹配到 `Order.order_no = "10000001"`
- **AND** `Order.order_id` 从 NULL 写为 `"916460217"`
- **AND** `Order.status` 由 `_infer_order_status` 推断(累计=0 + broker status 49 非撤单类 → 推断 49)
- **AND** `Order.traded_volume` 不变(累计由 trd_cfm 负责)

#### Scenario: ord_cfm 推送 broker status 为撤单类
- **WHEN** broker 推 `ord_cfm {remark: "10000001", order_id: "916460217", status: "53", ...}` 且本地 Order 累计=0
- **THEN** `_infer_order_status` 推断 `Order.status = "53"`(已撤)

#### Scenario: ord_cfm 推送 broker status 为撤单类 + 已有部分成交
- **WHEN** broker 推 `ord_cfm {remark: "10000001", order_id: "916460217", status: "53", ...}` 且本地 Order `traded_volume=500 < volume=1000`
- **THEN** `_infer_order_status` 推断 `Order.status = "56"`(部成部撤)

### Requirement: trd_cfm 推送用 remark 匹配 Order

`handle_trd_cfm` MUST 通过 broker 透传的 `remark` (= 本地 `order_no`) 匹配本地 Order(不再依赖 broker `order_id`);匹配到后 MUST 累计 `Order.traded_volume` / `Order.traded_amount`,重算 `avg_price`,调用 `_infer_order_status` 推断 `Order.status`。Trade 行 MUST 不论 Order 是否找到都 INSERT(数据先留存)。

#### Scenario: trd_cfm 首次成交
- **WHEN** broker 推 `trd_cfm {remark: "10000001", trade_id: "TID-001", volume: 300, price: 12.50, ...}`
- **AND** 本地存在 `Order.order_no = "10000001"`,`traded_volume=0, volume=1000`
- **THEN** 插入 `Trade.trade_id = "TID-001"`
- **AND** `Order.traded_volume = 300`
- **AND** `_infer_order_status` 推断 `Order.status = "50"`(部成)

#### Scenario: trd_cfm 累计后达到委托总量
- **WHEN** broker 推 `trd_cfm {remark: "10000001", trade_id: "TID-002", volume: 700, ...}`(累计后 1000)
- **AND** 本地 `Order.volume = 1000`
- **THEN** `Order.traded_volume = 1000`
- **AND** `_infer_order_status` 推断 `Order.status = "51"`(已成,终态)

#### Scenario: trd_cfm 重复推送去重
- **WHEN** broker 推 `trd_cfm {remark: "10000001", trade_id: "TID-001", ...}`(重复)
- **AND** DB 已存在 `Trade.trade_id = "TID-001"`
- **THEN** 后端 MUST NOT 重复插入
- **AND** MUST NOT 重复累计到 Order

#### Scenario: trd_cfm 找不到 Order(remark 缺失)
- **WHEN** broker 推 `trd_cfm` 不带 `remark` 字段
- **AND** 后端用 `remark` 查不到,`order_id` 兜底也查不到
- **THEN** Trade 行 MUST 仍插入(数据留存)
- **AND** 打印 `[trd_cfm] WARN: no order for trade_id=...`,Order 字段 MUST NOT 更新

### Requirement: 状态本地推断函数 _infer_order_status

系统 SHALL 提供 `_infer_order_status(order, broker_status=None)` 函数,根据 `order.traded_volume` / `order.volume` / `order.status`(当前值)和临时 `broker_status` 参数推断委托 status。

推断规则 SHALL 遵循:

1. **终态保持**:`order.status` 已是 `"51" "52" "53" "54" "55" "56"` 之一时,直接 return 当前值,不推断
2. **撤单类 broker_status**:`broker_status` 在 `"52" "53" "54"` 时:
   - 累计 = 0 → `"53"`(已撤)
   - 0 < 累计 < volume → `"56"`(部成部撤)
   - 累计 = volume → `"51"`(已成)
3. **累计推断**:
   - 累计 = 0 → `"49"`(已报)
   - 0 < 累计 < volume → `"50"`(部成)
   - 累计 = volume → `"51"`(已成)

#### Scenario: 推断函数纯函数矩阵(5 种)
- **WHEN** 调用 `_infer_order_status(Order(volume=1000, traded_volume=0), broker_status="49")` 且 Order.status 当前为非终态
- **THEN** return `"49"`
- **WHEN** 调用 `_infer_order_status(Order(volume=1000, traded_volume=0), broker_status="52")` 且 Order.status 当前为非终态
- **THEN** return `"53"`
- **WHEN** 调用 `_infer_order_status(Order(volume=1000, traded_volume=500), broker_status="52")` 且 Order.status 当前为非终态
- **THEN** return `"56"`
- **WHEN** 调用 `_infer_order_status(Order(volume=1000, traded_volume=1000), broker_status="52")` 且 Order.status 当前为非终态
- **THEN** return `"51"`
- **WHEN** 调用 `_infer_order_status(Order(volume=1000, traded_volume=300), broker_status=None)` 且 Order.status 当前为非终态
- **THEN** return `"50"`

#### Scenario: 终态保持
- **WHEN** `Order.status = "56"`(已是部成部撤终态),trd_cfm 累计一笔
- **THEN** `_infer_order_status` 直接 return `"56"`,MUST NOT 覆盖回 `"50"`(部成)
