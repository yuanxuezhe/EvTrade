# rpc-protocol delta — status 字典统一到 broker xtconstant

## MODIFIED Requirements

### Requirement: REQ-RPC-004.1 broker status 字段重映射（v11 新增段）

`qry_ord` 响应 `order_status` 字段值 MUST 直接写入 `Order.status`，无翻译层（v10 之前是"本地推断码语义", 现在是 broker 字典直接对齐）。`push_handler_ord` 收到 broker 推 `order_status` 字段 MUST 直接采用, 不调用任何翻译函数。字段名唯一权威: broker 原字段名 (`order_status`), 不再 alias `status`。

#### Scenario: qry_ord 响应 status 直接采用 broker 码（v11 新增）

- **WHEN** `qry_ord` 响应 RS2 含 `order_status='54'`（broker CANCELED）
- **THEN** API 层 Pydantic 序列化时映射为 `status='54'`
- **AND** 前端 view 按 broker 字典解读: `STATUS_LABEL['54']` = '已撤'
- **AND** 跨系统对账时无需翻译

#### Scenario: push handler 直接采用 broker order_status（v11 新增）

- **WHEN** broker 推 `ord_cfm` row 含 `order_status='57'`（broker JUNK 废单）
- **THEN** `push_handler_ord` 直接写 `Order.status='57'`, 不调用 `_status_msg` 翻译
- **AND** 前端 view 按 broker 字典解读: `STATUS_LABEL['57']` = '废单'

#### Scenario: 跨系统对账无需翻译（v11 新增）

- **WHEN** 对账脚本读取 broker `qry_ord` 响应 vs 本地 DB `orders.status`
- **THEN** broker `order_status='54'` 与本地 `status='54'` 是同一字典同一码, 无需翻译表

#### Scenario: qry_ord 字段映射（v11 修订）

- **WHEN** `qry_ord` 响应 RS2 包含 `order_status` 字段
- **THEN** 业务字段映射表 MUST 标记 `order_status` → `status` 直接采用 broker 码, 无翻译
- **AND** 之前的"本地推断码语义"层（`Status._LABEL` / `ORDER_STATUS` legacy / 前端 `STATUS_LABEL` 错位）全部废弃

## 备注

- 本次 change 不改 `qry_ord` / `qry_mch` / `qry_ast` / `qry_pos` 4 个查询端点的字段名, 仅修订 `order_status` 字段语义层
- 本次 change 不改 ws 推送协议字段名
- 旧 `Status._LABEL` / `Status.label()` / `_status_msg` 3 个翻译符号全部废弃, 详见 `push/spec.md` delta REQ-PUSH-005 段

## 勘误历史

- 2026-07-02 v11: status 字典统一到 broker xtconstant (align-status-codes-to-xtconstant)
  - qry_ord 响应 order_status 字段直接采用 broker 码
  - push_handler_ord 不再调用 `_status_msg` 翻译
  - 跨系统对账无需翻译表
  - `Status._LABEL` / `Status.label()` / `_status_msg` 3 个翻译符号全部废弃