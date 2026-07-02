# push delta — status 字典统一到 broker xtconstant

## MODIFIED Requirements

### Requirement: REQ-PUSH-005 status 字段语义（v11 broker 字典对齐）

后端写入 Order.status 时 MUST 采用 broker xtconstant 字典（11 条: 48-57 + 255），无本地扩展。`handle_ord_cfm` 直接采用 broker 推回；`handle_trd_cfm` 累计后调 `_infer_order_status` 推断输出码全集 {50, 53, 54, 55, 56}（全是 broker 码）。

#### Scenario: handle_trd_cfm 推断终态采用 broker 码

- **WHEN** Order.volume=100, traded_volume=50（部成）, handle_trd_cfm 累计后调 _infer_order_status
- **THEN** 输出 status='55'（broker 部成），不是本地推断码 50

#### Scenario: handle_ord_cfm broker 推回直接采用

- **WHEN** broker ord_cfm 推回 order_status='54'（broker 已撤）
- **THEN** handle_ord_cfm 直接采用 Order.status='54'，不再翻译

#### Scenario: 终态保持（含 broker 52）

- **WHEN** Order.status='52'（broker 部成待撤）或 '53'/'54'/'55'/'56'/'57'
- **THEN** handle_trd_cfm 累计后调 _infer_order_status 不覆盖该 status

#### Scenario: 业务写入点 broker 码（v9 cancel-row 短路）

- **WHEN** DELETE 端点 INSERT cancel-row (order_flag=1)
- **THEN** cancel-row.status 起手 '48'（本地 sentinel）
- **AND** DELETE 成功 → '54'（broker 已撤）
- **AND** DELETE 失败 → '57'（broker 废单）

#### Scenario: _infer_order_status 输出 broker 码

- **WHEN** _infer_order_status 推断终态
- **THEN** 输出码全集 {50, 53, 54, 55, 56}（全是 broker 码）
- **AND** broker_status 撤单类判定 `('52','53','54')` 不变（broker 码与本地巧合对齐）

### Requirement: REQ-PUSH-030 broker status 字段重映射表（v11 新增段）

push handler MUST 严格读 broker 原字段名（snake_case），与 parsers 层对齐；WS payload `status` 字段 MUST 是 broker xtconstant 数字字符串 (`'48'`...`'255'`)，含义与 xtconstant 字典一一对应。

#### Scenario: WS payload status 字段是 broker 码（v11 新增）

- **WHEN** WS `order_update` payload 含 status 字段
- **THEN** status 字段值必须是 broker xtconstant 字典之一 (48/49/50/51/52/53/54/55/56/57/255)
- **AND** 前端 view (Trade.vue / Orders.vue) 的 status 分组集合按 broker 字典定义
- **AND** 不再有"本地推断码"语义层 (旧本地码 49/50/51/53/56 全部对齐到 broker 码)

#### Scenario: push handler 字段名严格匹配 broker

- **WHEN** broker 推送 `trd_cfm` row 含 `traded_id` / `traded_volume` / `traded_price` / `traded_amount` / `traded_time`
- **THEN** `push_handler_trd.py` MUST 直接读 broker 原字段名（`row.get('traded_id')` 等），不允许 alias 兼容

#### Scenario: 旧 alias 字段已废弃

- **WHEN** developer 在 push handler 中写 `row.get('trade_id')`（老 alias）
- **THEN** code review MUST 拒收；正确写法为 `row.get('traded_id')`

#### Scenario: pos_cfm 字段名一致

- **WHEN** broker 推送 `pos_cfm` row 含 `avl_amt` / `avg_price`
- **THEN** `push_handler_pos.py` MUST 用 `row.get('avl_amt')` / `row.get('avg_price')`，不再 alias `available` / `cost_price`

#### Scenario: ast_cfm 字段名一致

- **WHEN** broker 推送 `ast_cfm` row 含 `frozen_cash`
- **THEN** `push_handler_ast.py` MUST 用 `row.get('frozen_cash')`，不再 alias `frozen`

### Requirement: REQ-PUSH-008 broker 字段映射补遗（v11 新增）

`broker ord_cfm` 不匹配 cancel-row 的判断条件中 `status` 字段值 MUST 是 broker 码；cancel-row 自身 status 由 DELETE 端点维护。

#### Scenario: cancel-row status 由 DELETE 端点维护（v11 修订）

- **WHEN** DELETE 端点 INSERT cancel-row (order_flag=1)
- **THEN** cancel-row.status 起手 '48'（broker UNREPORTED 本地 sentinel）
- **AND** DELETE 成功 → '54'（broker CANCELED 已撤）
- **AND** DELETE 失败 → '57'（broker JUNK 废单）
- **AND** WS broadcast payload 含 status='54' 或 '57', 前端 view 按 broker 字典解读

## 备注

- 旧 v8 规则 "broker_status in (52,53,54) → 撤单类信号" 中 broker_status 是 xtconstant 码, v11 起变成对齐
- TERMINAL_STATUSES 包含 broker 52 (部成待撤) 是 v11 决策点 #2: 与 broker 终态口径一致
- 业务写入点 10 处固定码改 broker 码, 详见 `trading/spec.md` delta REQ-TRADE-002 / REQ-TRADE-003 段
- 前端 5 张字典同步改 broker 义, 详见 `frontend/spec.md` delta

## 勘误历史

- 2026-07-02 v11: status 字典统一到 broker xtconstant (align-status-codes-to-xtconstant)
  - handle_ord_cfm 直接采用 broker order_status, 不再翻译
  - handle_trd_cfm 累计推断输出码全集 {50, 53, 54, 55, 56}
  - TERMINAL_STATUSES 改为 broker 终态口径
  - WS payload status 字段是 broker 码, 不再有本地推断码语义层