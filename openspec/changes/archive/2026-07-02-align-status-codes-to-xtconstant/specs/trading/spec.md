# trading delta — status 字典统一到 broker xtconstant

## MODIFIED Requirements

### Requirement: REQ-TRADE-002 下单（v11 broker 码）

`POST /api/orders/place` 业务写入点固定码 MUST 改 broker 码：
- `server/api/orders/place.py:90` 拒单 status: `'55'` (本地废单) → `'57'` (broker JUNK 废单)
- `server/api/orders/place.py:110` RPC 成功 status: `'49'` (本地已报) → `'50'` (broker REPORTED 已报)
- `server/api/orders/place.py:113` RPC 拒单 status: `'55'` (本地废单) → `'57'` (broker JUNK 废单)

委托表 `status` 字段 MUST 等于 broker xtconstant 委托状态（11 条: 48-57 + 255; 与 xtconstant 字典一一对应, 无本地扩展）。`TERMINAL_STATUSES = ('52','53','54','55','56','57')`（含 broker 52=部成待撤, 与 broker 终态口径一致）。

#### Scenario: place.py RPC 成功写入 broker 50（v11 修订）

- **WHEN** POST /api/orders/place 收到 `stock_code, order_type, volume, price, price_type` 且 RPC 返回 `code=0`
- **THEN** Order.status = `'50'`（broker REPORTED 已报），不是本地推断码 '49'

#### Scenario: place.py RPC 拒单写入 broker 57（v11 修订）

- **WHEN** POST /api/orders/place 收到 RPC 返回 `code != 0`（拒单）
- **THEN** Order.status = `'57'`（broker JUNK 废单），不是本地推断码 '55'

#### Scenario: place.py 同步写 cancelled_volume=volume（v8 不变）

- **WHEN** POST /api/orders/place 收到 RPC 返回 `code != 0`（拒单）
- **THEN** Order.cancelled_volume = Order.volume（一次性抹平, change `system-delegation-price-fill-calc` 起 5 类写入路径之一 R2a）

### Requirement: REQ-TRADE-003 撤单（v11 broker 码）

DELETE 端点业务写入点固定码 MUST 改 broker 码：
- `cancel.py:74` cancel-row 起手 status: `'48'` (本地 sentinel, 保留)
- `cancel.py:115` DELETE 成功 status: `'53'` (本地已撤) → `'54'` (broker CANCELED 已撤)
- `cancel.py:144` DELETE 失败 status: `'55'` (本地废单) → `'57'` (broker JUNK 废单)
- `cancel.py:61` pre-check `if order.status not in ("48","49")` → `("48","49","50")`（含 broker 50=已报）

#### Scenario: cancel.py DELETE 成功写入 broker 54（v11 修订）

- **WHEN** DELETE /api/orders/{order_no}?trd_date=YYYYMMDD 调用 RPC 返回 `ack.code == 0`
- **THEN** cancel-row.status = `'54'`（broker CANCELED 已撤），不是本地推断码 '53'

#### Scenario: cancel.py DELETE 失败写入 broker 57（v11 修订）

- **WHEN** DELETE /api/orders/{order_no}?trd_date=YYYYMMDD 调用 RPC 返回 `ack.code != 0` 或抛 Exception
- **THEN** cancel-row.status = `'57'`（broker JUNK 废单），不是本地推断码 '55'

#### Scenario: cancel.py pre-check 含 broker 50（v11 修订）

- **WHEN** DELETE /api/orders/{order_no}?trd_date=YYYYMMDD 调用, 原委托 status='50'（broker 已报）
- **THEN** pre-check 通过（status 在 {48, 49, 50} 内）, 进入 INSERT cancel-row + RPC 流程

#### Scenario: cancel.py pre-check 拒绝 broker 终态（v11 修订）

- **WHEN** DELETE /api/orders/{order_no}?trd_date=YYYYMMDD 调用, 原委托 status='54'（broker 已撤）
- **THEN** pre-check 拒绝（status 不在 {48, 49, 50} 内）, 返 `{code: NO_CANCELABLE}`, 不插行

#### Scenario: cancel.py 同步写原 cancelled_volume=volume（v11 修订 + R1 兜底）

- **WHEN** DELETE /api/orders/{order_no}?trd_date=YYYYMMDD 调用, RPC 返回 `ack.code == 0`
- **THEN** orig.cancelled_volume = orig.volume（一次性抹平, R1, change `system-delegation-price-fill-calc` 起 5 类写入路径之一）

### Requirement: REQ-TRADE-002.1 ord.py R2b 触发条件 broker 终态（v11 修订）

`server/services/push/ord.py` R2b 触发条件 MUST 用 broker xtconstant 终态口径:
- R2b 触发条件 `broker_status in ('53','55')` (本地已撤/本地废单) → `('52','53','54','55','56','57')` (broker 全部终态)
- rule 3 触发 `broker_status in ('52','53','54')` (本地撤单类) → `('51','52','53','54')` (broker 撤单类: 51=已报待撤, 52=部成待撤, 53=部成部撤, 54=已撤)

#### Scenario: ord.py R2b broker 终态触发（v11 修订）

- **WHEN** broker 推 `ord_cfm` row 含 `order_status='54'`（broker 已撤）
- **AND** Order.cancelled_volume < Order.volume
- **THEN** order.cancelled_volume = order.volume（R2b 抹平, change `system-delegation-price-fill-calc` 起 5 类写入路径之一）

#### Scenario: ord.py rule 3 broker 撤单类触发（v11 修订）

- **WHEN** broker 推 `ord_cfm` row 含 `order_status='52'`（broker 部成待撤）
- **THEN** _infer_order_status 触发 rule 3, 输出 status='54'（broker 已撤）或 '53'（broker 部成部撤）或 '56'（broker 已成），按 cum_traded 决定

## 备注

- 业务写入点 10 处固定码 + 2 处判定条件改 broker 码, 详见 `data-model/spec.md` delta
- WS payload `status` 字段是 broker 码 (数字字符串 `'48'`...`'255'`), 详见 `push/spec.md` delta REQ-PUSH-005 段
- 前端 5 张字典 + inferOrderStatus 同步改 broker 义, 详见 `frontend/spec.md` delta
- 历史 DB backfill SQL 6 条 (dev 仅 1 行需改), 详见 `data-model/spec.md` delta v11 业务规则补遗段
- 与 `tracking/2026-07-02-trades-amount-backfill` 一起组成维护窗口一次执行

## 勘误历史

- 2026-07-02 v11: status 字典统一到 broker xtconstant (align-status-codes-to-xtconstant)
  - place.py: 3 处固定码改 broker 码 (49→50, 55→57×2)
  - cancel.py: 3 处固定码改 broker 码 (53→54, 55→57, sentinel 48 不变) + pre-check 含 broker 50
  - ord.py: 2 处判定条件改 broker 终态 (R2b 触发 / rule 3 触发)
  - 共 10 处固定码 + 2 处判定条件改 broker 码
  - TERMINAL_STATUSES: `('51','52','53','54','55','56')` → `('52','53','54','55','56','57')` (含 broker 52)