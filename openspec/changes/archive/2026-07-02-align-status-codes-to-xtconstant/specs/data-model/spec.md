# data-model delta — status 字典统一到 broker xtconstant

## MODIFIED Requirements

### Requirement: orders.status 字段语义（v11 broker 字典对齐）

委托表 `status` 字段 MUST 采用 broker xtconstant 字典（11 条: 48-57 + 255），无本地扩展。

#### Scenario: orders.status 列定义采用 broker 字典

- **WHEN** 创建 Order ORM 模型
- **THEN** `status` 字段类型 `String(2)`, 默认 `"48"`, 注释为"broker xtconstant 委托状态（11 条: 48-57 + 255; 与 xtconstant 字典一一对应, 无本地扩展）"

#### Scenario: handle_trd_cfm 累计推断输出 broker 码

- **WHEN** Order.volume=100, traded_volume=50, handle_trd_cfm 累计后调 _infer_order_status
- **THEN** 输出 status='55'（broker 部成），不是本地推断码 50

#### Scenario: handle_ord_cfm 直接采用 broker 推回

- **WHEN** broker ord_cfm 推回 order_status='54'（broker 已撤）
- **THEN** handle_ord_cfm 直接采用 Order.status='54'，不再翻译

#### Scenario: 终态保持（含 broker 52）

- **WHEN** Order.status 已是 `'52'` / `'53'` / `'54'` / `'55'` / `'56'` / `'57'` 任一
- **THEN** handle_trd_cfm 累计后调 _infer_order_status 不再覆盖该 status

#### Scenario: cancel-row 起手 sentinel

- **WHEN** DELETE 端点 INSERT cancel-row (order_flag=1)
- **THEN** cancel-row.status = `'48'`（本地私有 sentinel，broker 不关心 cancel-row）
- **AND** DELETE 成功 → cancel-row.status = `'54'`（broker 已撤）；DELETE 失败 → cancel-row.status = `'57'`（broker 废单）

### Requirement: orders.status TERMINAL_STATUSES 集合（v11 broker 终态口径）

`server/services/order_status.py:TERMINAL_STATUSES` MUST 等于 `('52','53','54','55','56','57')`（broker xtconstant 终态口径）。

#### Scenario: TERMINAL_STATUSES 含 broker 52

- **WHEN** _infer_order_status 检查 current 是否为终态
- **THEN** broker 52（部成待撤）也算终态, 不会被 trd_cfm 累计覆盖
- **AND** 旧本地 `('51','52','53','54','55','56')` 集合作废, 51（broker 已报待撤）不再算终态

#### Scenario: Status.is_cancellable 含 broker 50

- **WHEN** 业务检查订单是否可撤
- **THEN** Status.is_cancellable 触发码 `('48','49','50')`（含 broker 50=已报也可撤）

### Requirement: orders.status 历史 DB backfill（v11 一次性）

历史 DB 数据 MUST 一次性 backfill 到 broker xtconstant 字典。6 条 SQL 在维护窗口内执行（与 `tracking/2026-07-02-trades-amount-backfill` 一起）。

#### Scenario: backfill SQL 覆盖 6 个本地码映射

- **WHEN** 维护窗口内执行 6 条 SQL：
  - `UPDATE orders SET status = '54' WHERE status = '53' AND order_flag = 1`（cancel-row 已撤）
  - `UPDATE orders SET status = '57' WHERE status = '55'`（废单）
  - `UPDATE orders SET status = '56' WHERE status = '51'`（已成）
  - `UPDATE orders SET status = '55' WHERE status = '50'`（部成）
  - `UPDATE orders SET status = '50' WHERE status = '49'`（已报）
  - `UPDATE orders SET status = '53' WHERE status = '56'`（本地 部成部撤 → broker 部成部撤）
- **THEN** backfill 后 `SELECT status, COUNT(*) FROM orders GROUP BY status` 分布与 broker 字典一致
- **AND** 48（sentinel）不动
- **AND** dev DB 仅 1 行需改（已通过 `scripts/dry_run_status_distribution.py` 验证）

#### Scenario: backfill 时机

- **WHEN** 部署 commit 1-4 + DB backfill
- **THEN** 必须同次部署 + 同维护窗口, 否则前端字典 broker 码 vs DB 本地码不一致 → 视图层显示错位

## 备注

- 本次 change 不改 DB schema（`status` 字段类型 `String(2)` 不变）
- 不改 API 入参/出参形状（`OrderOut.status` 字段名不变，仅数字含义变化）
- 不改 ws 推送协议字段名
- 前端 `format.js` 的 5 张字典同步改 broker 义，详见 `frontend/spec.md` delta
- 前端 fall-back 兼容 key（`unreported` / `filled` / `cancelled` 等 14 个英文 key）全部删除, 详见 `frontend/spec.md` delta

## 勘误历史

- 2026-07-02 v11: status 字典统一到 broker xtconstant (align-status-codes-to-xtconstant)
  - 删除本地扩展 56（部成部撤）→ broker 53
  - TERMINAL_STATUSES: `('51','52','53','54','55','56')` → `('52','53','54','55','56','57')`
  - 业务写入点改 broker 码（10 处固定码 + 2 处判定条件）
  - 历史 DB 一次性 backfill (6 条 SQL)