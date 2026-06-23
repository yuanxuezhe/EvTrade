# data-model — 本地 SQLite 表结构知识库

## Purpose

11 张表（业务 4 + 配置 4 + 历史 1 + 行情 1 + 序列 1）的**单一事实源**（single source of truth）。
任何表结构变更（加列、改类型、调 PK、改约束）必须先改本 spec，再同步到 `server/models/orm.py` 和 `server/db.py`。
ORM 注释必须与本 spec 保持一致（diff 检查项之一）。

设计原则（v5 schema-refactor）：

- **snake_case**：表名、列名一律小写下划线
- **trd_date**：8 位数字字符串 `YYYYMMDD`，含 trd_date 的表必须入主键（按交易日维度定位）
- **单行表**：用 `id=1` + `CheckConstraint("id = 1")`，业务约定 `.first()` 访问
- **数值归零**：所有 Float/Integer 默认 `0.0` / `0`，避免空值歧义
- **状态码**：订单/持仓等用字符串（`status="48"..`）保持与柜台 wire format 一致
- **复合业务键替代自增 id**：如 `(trd_date, order_no)` / `(stock_code,)`，`id` 仅在必须时使用

## Tables Overview

| # | 表 | 分类 | 主键 | 单行？ | 业务入口 |
|---|---|---|---|---|---|
| 1 | `orders` | 业务 | `(trd_date, order_no)` | 否 | `server/api/orders.py` |
| 2 | `trades` | 业务 | `(trd_date, order_no, trade_id)` | 否 | `server/api/trades.py` |
| 3 | `positions` | 业务 | `stock_code` | 否（多股） | `server/api/positions.py` |
| 4 | `assets` | 业务 | `id=1` 约束 | ✅ 单行 | `server/api/asset.py` |
| 5 | `sys_status` | 配置 | `trd_date` | 否（多日） | `server/services/trading_day.py` |
| 6 | `trading_session` | 配置 | `id=1` 约束 | ✅ 单行 | `server/services/guards.py` |
| 7 | `fee_config` | 配置 | `id=1` 约束 | ✅ 单行 | `server/services/t0.py` |
| 8 | `reconcile_config` | 配置 | `id=1` 约束 | ✅ 单行 | `server/services/reconcile.py` |
| 9 | `reconcile_report` | 历史 | `(trd_date, mode, created_at)` | 否 | `server/services/reconcile.py` |
| 10 | `quote_snapshots` | 行情 | `id` 自增 | 否 | `server/api/quote.py`（若有） |
| 11 | `order_no_seq` | 序列 | `id=1` 约束 | ✅ 单行 | `server/services/order_no.py` |

## Table Details

### 1. `orders` — 委托主表

**PK**: `(trd_date, order_no)`（v6 改：order_id 退 PK，进普通可空列）

| 字段 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| `trd_date` | String(8) | NO | — | 交易日 PK |
| `order_no` | String(8) | NO | — | 本地 8 位序号 PK（10000000 起） |
| `order_id` | String(64) | YES | NULL | 柜台真实委托号（ord_cfm 到达时写入；下单时为空） |
| `user_def` | String(255) | NO | "" | 外部自定义信息（前端幂等号 / 备注等，不做幂等约束） |
| `stock_code` | String(16) | NO | — | 股票代码 |
| `order_type` | String(2) | NO | — | 23=买 24=卖 |
| `price_type` | Integer | NO | 11 | 5/11/14/44 详见 trading spec |
| `price` | Float | NO | 0.0 | 委托价 |
| `volume` | Integer | NO | 0 | 委托量 |
| `traded_volume` | Integer | NO | 0 | 累计成交量 |
| `traded_amount` | Float | NO | 0.0 | 累计成交额 |
| `avg_price` | Float | NO | 0.0 | 成交均价 = traded_amount / traded_volume |
| `cancelled_volume` | Integer | NO | 0 | **累计撤单量**（v8 新增：broker ord_cfm 累加；用于推断已撤/部成部撤） |
| `order_flag` | Integer | NO | 0 | **v9 新增**：`0`=正常委托，`1`=撤单委托（DELETE 端点 INSERT 的本地代理行；broker 不会推送该 row） |
| `status` | String(2) | NO | "48" | **本地推断的委托状态**（48/49/50/51/52/53/54/55/56） |
| `status_msg` | String(255) | NO | "" | 状态中文或 broker 错误信息 |
| `order_time` | String(8) | NO | "" | HH:MM:SS |
| `created_at` | DateTime | NO | utcnow | DB 写入时间 |
| `updated_at` | DateTime | NO | utcnow | onupdate=utcnow |
| `pushed_at` | DateTime | YES | NULL | 最近一次 broker push 写入时间 |

**Unique/Index**:
- ~~`uq_orders_client_trd`~~ — **v7 删除**（幂等不再走 client_order_id 唯一约束；走 `order_no` 唯一 + RPC 返回确认）
- ~~`uq_orders_broker_id(order_id, trd_date)`~~ — **v7 删除**（order_id 在下单时为空，不能进 UNIQUE；broker 定位用 `ix_orders_order_id` 普通索引）
- `ix_orders_trd_status(trd_date, status)` — 按状态过滤
- `ix_orders_order_id(order_id)` — trd_cfm 兜底定位
- `ix_orders_stock(stock_code)` — 按股票过滤

**业务规则**:
- `status` 永远不直接抄 broker 推送值；由 `_infer_order_status(order, broker_status=None)` 推断（见 `push/spec.md`）
- 终态（51/52/53/54/55/56）一旦写入不再被 trd_cfm 覆盖
- 撤单定位用 `(trd_date, order_no)`，URL `/api/orders/{order_no}?trd_date=YYYYMMDD`
- **v9 schema 调整**：
  - 新增 `order_flag` 字段：`0`=正常委托，`1`=撤单委托占位行（DELETE 端点 INSERT，由 DELETE 端点全权管理 status；broker `ord_cfm` 永远不会 match 到 cancel-row——broker 推 `remark` 永远是原委托 order_no，不是新 cancel-row 的 order_no）
  - cancel-row 字段填充：`stock_code/order_type/price_type/price` 镜像原委托；`volume=0`；`status` 起步 `48`，RPC 成功 → `53`，RPC 失败 → `55`
  - DB 迁移脚本：`ALTER TABLE orders ADD COLUMN order_flag INTEGER NOT NULL DEFAULT 0`
- **v8 schema 调整**：
  - 新增 `cancelled_volume` 字段：累计撤单量，broker ord_cfm 推送 `cancelled_volume` / `cancel_volume` / `withdrawn_volume` 任一字段名时累加（兼容多版本）
  - 状态推断规则改：`cancelled_volume >= volume` → 53（已撤）；`cancelled_volume > 0 && traded_volume > 0` → 56（部成部撤）；`cancelled_volume > 0` → 53
  - DB 迁移脚本：`ALTER TABLE orders ADD COLUMN cancelled_volume INTEGER NOT NULL DEFAULT 0`
- **v7 schema 调整动机**：
  - `client_order_id` UNIQUE 约束无法用 — order_id 下单时为空，对应 broker 约束才能稳定
  - `user_def` 是纯透传字段（前端可写可读），不参与任何 DB 约束
  - `order_no` 本身就是 8 位唯一序号，下单流程幂等靠 RPC 客户端 `client_order_id` 透传 + 后端落表前查重（应用层去重）

### 2. `trades` — 成交表

**PK**: `(trd_date, order_no, trade_id)`（**v7 改**：加入 `order_no` 入 PK，移除 `order_id`）

| 字段 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| `trd_date` | String(8) | NO | — | 交易日 PK |
| `order_no` | String(8) | NO | — | 关联本地委托号 PK（→ orders.order_no） |
| `trade_id` | String(64) | NO | — | 成交编号 PK（broker 唯一） |
| `stock_code` | String(16) | NO | — | 股票代码 |
| `order_type` | String(2) | NO | — | 23/24 |
| `price` | Float | NO | 0.0 | 成交价 |
| `volume` | Integer | NO | 0 | 成交量 |
| `amount` | Float | NO | 0.0 | 成交额 = price × volume |
| `trade_time` | String(8) | NO | "" | HH:MM:SS |
| `trade_type` | Integer | NO | 0 | **v9 新增**：`0`=正常成交，`1`=撤单成交（DELETE 端点撤单成功时同步生成，volume=剩余可撤；不参与 buy/sell 统计） |
| `created_at` | DateTime | NO | utcnow | DB 写入时间 |

**Index**:
- `ix_trades_order_no(order_no)` — **v7 重命名**（原 `ix_trades_order(order_id)` 改为按本地 order_no 查）
- `ix_trades_trd_stock(trd_date, stock_code)` — 按股票查当日

**业务规则**:
- 幂等键 `(trd_date, trade_id)`；重复推送不重复插入
- trade_id 缺失时 fallback `f"{order_no}-{trade_time}"`
- trd_date 缺失时用 `_get_active_trd_date(db)`
- **v9 schema 调整**：
  - 新增 `trade_type` 字段：`0`=normal，`1`=cancel-fill（DELETE 端点撤单成功时同步生成的撤单成交占位行）
  - cancel-fill 字段填充：`volume = orig.volume - orig.traded_volume`（剩余可撤股数）；`price = orig.avg_price or orig.price`；`trade_id = "CANCEL-{cancel_order_no}-{unix_ts}"` 合成；`order_no` 关联 cancel-row（不是原委托）
  - DB 迁移脚本：`ALTER TABLE trades ADD COLUMN trade_type INTEGER NOT NULL DEFAULT 0`
- **v7 schema 调整动机**：
  - `order_no` 是稳定关联键（下单即生成，写入即永久），`order_id` 在成交回报到达时可能尚未到达
  - 成交回报通常早于 ord_cfm，用本地 order_no 关联比 broker order_id 更稳
  - `order_no` 入 PK 同时保证 (trd_date, order_no) 下成交唯一，避免同一委托多次成交的重复插入风险

### 3. `positions` — 持仓表

**PK**: `stock_code`

| 字段 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| `stock_code` | String(16) | NO | — | PK（单股唯一） |
| `stock_name` | String(64) | NO | "" | 股票名 |
| `last_vol` | Integer | NO | 0 | **期初持仓**（对账时设置） |
| `today_buy` | Integer | NO | 0 | 今日买入累计（对账时设置） |
| `today_sell` | Integer | NO | 0 | 今日卖出累计（对账时设置） |
| `avl_vol` | Integer | NO | 0 | **可用**持仓 |
| `vol` | Integer | NO | 0 | **总持仓**（= last_vol + today_buy - today_sell） |
| `cost_price` | Float | NO | 0.0 | 持仓成本价 |
| `synced_at` | DateTime | NO | utcnow | 最近同步时间 |
| `synced_from` | String(16) | NO | "" | `rpc_full` / `push_pos_cfm` / `manual` |

**业务规则**:
- `vol` 的数据源：pos_cfm 推送 → `row.volume` 字段（**缺字段时兜底为 `avl_vol`**，见 change `2026-06-16-fix-position-vol-display`）
- `last_vol` / `today_buy` / `today_sell` **只能由 do_reconcile 设置**；pos_cfm 不写
- `market_value` 不存；前端用 `quote.last_price * vol` 实时算
- 持仓多股；表无 trd_date（当前快照语义）

### 4. `assets` — 资金表

**PK**: `id=1`（`CheckConstraint("id = 1")` 强制单行）

| 字段 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| `id` | Integer | NO | 1 | PK + 单行约束 |
| `cash` | Float | NO | 0.0 | 可用资金 |
| `frozen_cash` | Float | NO | 0.0 | 冻结资金 |
| `market_value` | Float | NO | 0.0 | 持仓市值（前端实时覆盖） |
| `total_asset` | Float | NO | 0.0 | 总资产 = cash + frozen_cash + market_value |
| `synced_at` | DateTime | NO | utcnow | 最近同步时间 |
| `synced_from` | String(16) | NO | "" | `rpc_full` / `push_ast_cfm` / `manual` |

**业务规则**:
- 业务访问 `db.query(Asset).first()` / `db.delete()` + `db.add(new)`
- 单行约束 → 不保留历史资产快照（设计取舍，参见 issue L9）

### 5. `sys_status` — 系统级状态机

**PK**: `trd_date`

| 字段 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| `trd_date` | String(8) | NO | — | 交易日 PK |
| `status` | String(16) | NO | "pending" | `pending` / `active` / `closed` |
| `is_half_day` | Integer | NO | 0 | 0=全日 1=半日 |
| `initialized_at` | DateTime | YES | NULL | 日初完成时间 |
| `initialized_by` | Integer | YES | NULL | FK users.id |
| `closed_at` | DateTime | YES | NULL | 日终时间 |
| `closed_by` | Integer | YES | NULL | FK users.id |
| `remark` | String(255) | NO | "" | 备注 |
| `created_at` | DateTime | NO | utcnow | 创建时间 |

**Index**: `ix_sys_status_status(status)` — 查激活日

**业务规则**:
- 任意时刻最多 1 行 `status='active'`
- `INIT/CLOSE/RECONCILE` 状态机转换：`pending → active → closed`
- 路由前缀：`/api/admin/sys-status*`（v5 重命名，原 `/trading-day*`）

### 6. `trading_session` — 交易时段

**PK**: `id=1`（`CheckConstraint("id = 1")` 强制单行）

| 字段 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| `id` | Integer | NO | 1 | PK |
| `morning_start` | Time | NO | — | 09:15 |
| `morning_end` | Time | NO | — | 11:30 |
| `afternoon_start` | Time | NO | — | 13:00 |
| `afternoon_end` | Time | NO | — | 15:00 |
| `updated_at` | DateTime | NO | utcnow | |

### 7. `fee_config` — 费率配置

**PK**: `id=1`（`CheckConstraint("id = 1")` 强制单行）

| 字段 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| `id` | Integer | NO | 1 | PK |
| `commission_rate` | Float | NO | 0.0001 | 万一 |
| `stamp_tax_rate` | Float | NO | 0.001 | 千 1（仅卖出） |
| `slippage` | Float | NO | 0.001 | 0.1% 滑点 |
| `min_commission` | Float | NO | 5.0 | 最低 5 元 |
| `updated_at` | DateTime | NO | utcnow | |
| `updated_by` | Integer | YES | NULL | FK users.id |

### 8. `reconcile_config` — 对账配置

**PK**: `id=1`（`CheckConstraint("id = 1")` 强制单行）

| 字段 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| `id` | Integer | NO | 1 | PK |
| `auto_reconcile` | Integer | NO | 0 | 0=人工 1=自动 |
| `auto_use_broker_data` | Integer | NO | 1 | 自动时 1=以柜台为准 0=以本地为准 |
| `updated_at` | DateTime | NO | utcnow | |
| `updated_by` | Integer | YES | NULL | FK users.id |

### 9. `reconcile_report` — 对账历史报告

**PK**: `(trd_date, mode, created_at)`

| 字段 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| `trd_date` | String(8) | NO | — | 交易日 PK |
| `mode` | String(16) | NO | — | `auto` / `manual` PK |
| `created_at` | DateTime | NO | utcnow | PK（同 mode 同日可多次） |
| `diffs_json` | Text | NO | "[]" | 差异明细 JSON |
| `broker_asset_json` | Text | NO | "" | 柜台资金快照 |
| `local_asset_json` | Text | NO | "" | 本地资金快照 |
| `broker_positions_json` | Text | NO | "" | 柜台持仓快照 |
| `local_positions_json` | Text | NO | "" | 本地持仓快照 |
| `rpc_status` | String(16) | NO | "ok" | `ok` / `partial` / `failed` |
| `error_message` | String(512) | NO | "" | 错误信息 |
| `created_by` | Integer | YES | NULL | FK users.id |

**Index**: `ix_reconcile_report_trd(trd_date)` — 按日查

### 10. `quote_snapshots` — 行情快照

**PK**: `id` 自增

| 字段 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| `id` | Integer | NO | autoincrement | PK |
| `stock_code` | String(16) | NO | — | 股票代码 |
| `last_price` | Float | NO | 0.0 | 最新价 |
| `open_price` / `high_price` / `low_price` / `prev_close` | Float | NO | 0.0 | OHLC |
| `volume` | Integer | NO | 0 | 累计成交量 |
| `amount` | Float | NO | 0.0 | 累计成交额 |
| `bid1_price` .. `ask5_price` | Float | NO | 0.0 | 五档盘口价 |
| `bid1_vol` .. `ask5_vol` | Integer | NO | 0 | 五档盘口量 |
| `ts` | DateTime | NO | utcnow | 快照时间（index=True） |

**Index**: `ix_quote_stock_ts(stock_code, ts)` — 按股票+时间查

**业务规则**:
- 由 hqserver 定期写入；前端不直接读此表（用 WS 推送）

### 11. `order_no_seq` — 订单序号生成器

**PK**: `id=1`（`CheckConstraint("id = 1")` 强制单行）

| 字段 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| `id` | Integer | NO | 1 | PK |
| `last_value` | Integer | NO | 10000000 | 8 位起 |
| `updated_at` | DateTime | NO | utcnow | onupdate=utcnow |

**业务规则**:
- `next_order_no(db)` 原子 UPSERT + 返回 `last_value + 1`
- 8 位数字，超过 99999999 后溢出（实务不会发生）

## Modification Workflow

修改任何表结构时：

1. **改本 spec**：先在本文件相应表的字段表中改，明确类型/PK/默认值
2. **改 ORM**：`server/models/orm.py` 同步（diff 必须 0 除注释）
3. **改 API/service**：消费方按新 schema 改（如有）
4. **改测试**：`server/test_models.py` 等加回归
5. **重建 DB**：dev 期 `rm server/evtrade.db`，生产需手工迁移（无 Alembic）
6. **commit 前 grep 自检**：
   ```bash
   grep -rE "order_remark|TRD_DATE|current_date|initial_position|TRD_DATE" server/ client/src/ --include="*.py" --include="*.vue" --include="*.js"
   ```
   应只命中 `archive/` 或本 spec。

## Cross-References

- 委托/成交/资金 API：`specs/trading/spec.md`
- 持仓 API：`specs/positioning/spec.md`
- 推送落库：`specs/push/spec.md`
- 前端缓存层：`specs/frontend/spec.md`
- 改 schema 的具体 change 提案：见 `changes/2026-06-16-*/proposal.md`
