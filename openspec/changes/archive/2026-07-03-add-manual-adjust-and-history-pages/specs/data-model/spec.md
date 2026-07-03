## ADDED Requirements

### Requirement: Position 表结构（v12 删除 today_buy / today_sell 死字段）

`Position` 表 MUST 移除 `today_buy` / `today_sell` 两列以及对应的"由对账时设置"业务规则段。**breaking change** —— 已有 DB 需迁移脚本。

#### Scenario: 移除 today_buy 列

- **WHEN** 实施本 change
- **THEN** `server/models/orm.py:Position` 不再含 `today_buy` 列
- **AND** 数据迁移脚本 `ALTER TABLE positions DROP COLUMN today_buy` 在 dev/prod 都执行

#### Scenario: 移除 today_sell 列

- **WHEN** 实施本 change
- **THEN** `server/models/orm.py:Position` 不再含 `today_sell` 列
- **AND** 数据迁移脚本 `ALTER TABLE positions DROP COLUMN today_sell` 在 dev/prod 都执行

#### Scenario: 业务规则段同步删除

- **WHEN** 改 `data-model/spec.md` 表 3 字段表
- **THEN** 移除"由 do_reconcile 设置"段（包括今天买入累计 / 今天卖出累计 2 行）
- **AND** `Position` 字段表只保留 `last_vol`（期初）/ `avl_vol`（可用）/ `vol`（总持仓）/ `cost_price`

#### Scenario: 当日买卖累计语义改由 Trade 表聚合

- **WHEN** 前端需要知道"今日买入总量"
- **THEN** 用 `Trade` 表的 `Order.trd_date = active_day AND order_type = '23' SUM(volume)` 替代
- **AND** 不需要在 `Position` 表持有冗余累计字段

### Requirement: Position 调平入口不存 delta 字段（v12）

`Position` 表 MUST NOT 新增 `manual_offset_vol` / `manual_offset_cash` 之类的 delta 字段。手动调平通过原子修改现有的 `vol` / `avl_vol` / `cash` / `total_asset` 四个总量字段实现，详见 `asset-position-adjust/spec.md`。

#### Scenario: 调平后字段直接体现

- **WHEN** admin 调平 `Position.vol += 100`
- **THEN** 前端读到的 `Position.vol` 是 broker 全量 + trd_cfm 增量 + 100（即新当前值）
- **AND** 不会被下次 day_init reconcile 抹掉之外被覆盖前一直生效

#### Scenario: synced_from 标记 manual 调平

- **WHEN** admin 调用 `PUT /api/positions/{stock_code}/adjust`
- **THEN** `Position.synced_from = "manual"` + `Position.synced_at = utcnow`
- **AND** `synced_from` 可用于前端 UI 提示"该行被人工调平过"
