# data-model — MySQL 表结构知识库（v80.2 起 v14 sqlite→mysql）

## Purpose

15 张表（业务 6 + 策略/脚本 3 + 系统/用户 4 + 对账/序列 2）的**单一事实源**（single source of truth）。
任何表结构变更（加列、改类型、调 PK、改约束）必须先改本 spec，再同步到 `server/schema.yml`，然后跑 `python scripts/sync_schema.py apply` 推 DB + 重新生成 `server/tables/<表名>.py`。

ORM 注释（`server/tables/<表名>.py` 自动生成）必须与本 spec 保持一致（diff 检查项之一）。

> **历史注**：v14 之前项目用 SQLite，自 v20 起强制 MySQL-only。本 spec 早期版本描述 SQLite 时代，标题虽沿用旧名，但所有 schema 都已迁移到 MySQL。

设计原则（v5 schema-refactor，v80.2 调整）：

- **snake_case**：表名、列名一律小写下划线
- **trd_date**：8 位数字字符串 `YYYYMMDD`，含 trd_date 的表必须入主键（按交易日维度定位）
- **单行表**：用 `id=1` + `CheckConstraint("id = 1")`，业务约定 `.first()` 访问
- **数值归零**：所有 Float/Integer 默认 `0.0` / `0`，避免空值歧义
- **状态码**：订单/持仓等用字符串（`status="48"..`）保持与柜台 wire format 一致
- **复合业务键替代自增 id**：如 `(trd_date, order_no)` / `(stock_code,)`，`id` 仅在必须时使用
- **v12 schema 调整**（change `add-manual-adjust-and-history-pages`）：
  - `positions` 表移除 `today_buy` / `today_sell` 两列（v5 引入以来从未被消费的死字段）
  - `assets` / `positions` 的 `synced_from` 新增 `'manual'` 取值（admin 调平写入标记）
  - DB 迁移脚本：`scripts/migrations/2026-07-03-drop-position-today-buy-sell.sql`

## Tables Overview

按业务域分组（共 14 张业务表 + 1 张 `order_no_seq` 序列表）：

### 📊 业务核心（v4 数据本地优先：本地 DB 是展示源）

| # | 表 | 分类 | 主键 | 单行？ | 业务入口 |
|---|---|---|---|---|---|
| 1 | `orders` | 业务 | `(trd_date, order_no)` | 否 | `server/api/orders/` |
| 2 | `trades` | 业务 | `(trd_date, order_no, trade_id)` | 否 | `server/api/trades.py` |
| 3 | `positions` | 业务 | `stock_code` | 否（多股） | `server/api/positions.py` |
| 4 | `assets` | 业务 | `id=1` 约束 | ✅ 单行 | `server/api/asset.py` |
| 5 | `t0_tasks` | 业务 | `id` | 否 | `server/api/t0_tasks.py` |
| 6 | `quote_snapshots` | 行情 | `id` 自增 | 否 | `server/api/quote.py` |

### 🎯 策略体系（v90 script-strategy change 起；v66 网格引擎 2026-08-10 已删）

| # | 表 | 分类 | 主键 | 单行？ | 业务入口 |
|---|---|---|---|---|---|
| 7 | `strategy_task` | 策略 | `id` 自增 | 否 | `server/api/script_strategy/endpoints.py` |
| 8 | `strategy_script` | 脚本 | `(user_id, id)` 复合 | 否 | `server/api/script_strategy/endpoints.py` |
| 9 | `strategy_script_audit` | 脚本 | `id` 自增 | 否 | `server/api/script_strategy/endpoints.py` |

### 🔐 系统/用户

| # | 表 | 分类 | 主键 | 单行？ | 业务入口 |
|---|---|---|---|---|---|
| 10 | `users` | 系统 | `id` 自增 | 否 | `server/api/users.py` |
| 11 | `sys_status` | 系统 | `trd_date` | 否（多日） | `server/services/trading_day.py` |
| 12 | `sys_config` | 系统 | `(user, cfg_key)` 复合 | 否 | `server/api/sysconfig.py` |
| 13 | `stocks` | 系统 | `stock_code` | 否（多股） | `server/api/stocks.py` |

### 📋 日初对账 / 序列表

| # | 表 | 分类 | 主键 | 单行？ | 业务入口 |
|---|---|---|---|---|---|
| 14 | `reconcile_report` | 历史 | `(trd_date, mode, created_at)` | 否 | `server/services/reconcile.py` |
| 15 | `order_no_seq` | 序列 | `id` 约束 | ✅ 单行 | `server/services/order_no.py` |

> **变更说明**：
> - v14 起从 SQLite 迁到 MySQL（v20 强制 MySQL-only）；本 spec 早期版本描述 SQLite 时代
> - v66 strategy_trade change：新增 `strategy` / `strategy_task` / `strategy_grid` / `strategy_regime` / `strategy_audit` 5 张策略表（**其中 4 张网格引擎表已随 v120.5 删除**）
> - v90 script-strategy change（2026-08-01）：新增 `strategy_script` / `strategy_script_audit` 2 张脚本策略表 + 扩展 `strategy_task` 字段
> - **v120.5 grid-engine-removal（2026-08-10）**：DROP `strategy` / `strategy_regime` / `strategy_grid` / `strategy_audit` / `stocks_legacy` 5 张表（migration `server/migrations/2026-08-10-drop-legacy-strategy-tables.py`，commit `aa70dae`）。网格引擎被脚本策略取代；schema.yml 同步移除 4 张表定义（19 → 15 张）
> - v120 strategy-exec-service change（2026-08-09）：`strategy_task` 加 3 字段 `execution_service`（'evtrade'/'strategy_exec'）/ `execution_pid` / `version`（乐观锁，migration `2026-08-09-strategy-task-exec-fields.py`）。运行引擎迁到独立服务 `strategy_exec/`；其 `progress` / `live_signals` / `status` 由 strategy_exec 写（`WHERE version=:v` 乐观锁，见 [`strategy-exec/spec.md`](../strategy-exec/spec.md) REQ-SE-007），EvTrade 侧 `strategy_script` / `strategy_script_audit` 只读、`strategy_task` 仅 `signal_consumer` 消费侧写 `status`/`order_no`
> - **v122 strategy-params-sweep-best-live（2026-08-10）**：`strategy_task` 加 3 sweep 列 `sweep_id VARCHAR(32) NULL` / `sweep_metric VARCHAR(32) NULL` / `sweep_total INT NULL`（migration `2026-08-11-add-strategy-sweep-fields.py`，commit `6808e8b`）。同 sweep 多 task 共享 `sweep_id`；summary task 也带 `sweep_id`（用 `sweep_total=1` 区分自身）。前端按 `sweep_id IS NULL` 判断单 run。详见 [`strategy-exec/spec.md`](../strategy-exec/spec.md) REQ-SE-008 / [`strategy/spec.md`](../strategy/spec.md) REQ-STRAT-016 扩展
> - v18 t0_tasks change：新增 `t0_tasks` 表（v18）+ `orders.task_id` 列
> - v23 slim-stocks-table：精简 `stocks` 字段

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
| `price_type` | Integer | NO | 0 | 0/1/2 详见 trading spec（v__: 与 xtconstant 柜台协议 1:1 对齐） |
| `price` | Float | NO | 0.0 | 委托价 |
| `volume` | Integer | NO | 0 | 委托量 |
| `traded_volume` | Integer | NO | 0 | 累计成交量 |
| `traded_amount` | Float | NO | 0.0 | 累计成交额 |
| `avg_price` | Float | NO | 0.0 | 成交均价 = traded_amount / traded_volume |
| `cancelled_volume` | Integer | NO | 0 | **累计撤单量**（v8 新增：broker ord_cfm 累加；用于推断已撤/部成部撤；change `system-delegation-price-fill-calc` 起 5 类写入路径统一抹平语义，详见业务规则） |
| `order_flag` | Integer | NO | 0 | **v9 新增**：`0`=正常委托，`1`=撤单委托（DELETE 端点 INSERT 的本地代理行；broker 不会推送该 row） |
| `status` | String(2) | NO | "48" | **v11 broker 字典对齐**：broker xtconstant 委托状态（11 条: 48-57 + 255; 与 xtconstant 字典一一对应, 无本地扩展） |
| `status_msg` | String(255) | NO | "" | 状态中文或 broker 错误信息 |
| `order_time` | String(23) | NO | "" | **v10 改**：`"YYYY-MM-DD HH:MM:SS.fff"` 完整日期时间（含毫秒，便于跨日委托归属 / 排序） |
| `created_at` | DateTime | NO | utcnow | DB 写入时间 |
| `updated_at` | DateTime | NO | utcnow | onupdate=utcnow |
| `pushed_at` | DateTime | YES | NULL | 最近一次 broker push 写入时间 |
| `raw_id` | String(8) | YES | NULL | **v13 NEW**：被撤/被引用委托的本地 order_no；DELETE 端点 INSERT cancel-row 时写入 = 原委托 order_no；非 cancel-row 为 NULL；旧数据全 NULL（迁移脚本 `server/migrations/2026-07-06-add-orders-raw-id.py`） |

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
- **v11 broker 字典对齐**（change `align-status-codes-to-xtconstant`）：
  - `status` 字段 MUST 等于 broker xtconstant 字典（11 条: 48-57 + 255; 无本地扩展）
  - 终态集合（`server/services/order_status.py:TERMINAL_STATUSES`）MUST 等于 `('52','53','54','55','56','57')`（broker xtconstant 终态口径, 含 broker 52=部成待撤）
  - 旧本地 `('51','52','53','54','55','56')` 集合作废；51（broker 已报待撤）不再算终态
  - `Status.is_cancellable` 触发码 `('48','49','50')`（含 broker 50=已报也可撤）
  - handle_ord_cfm 直接采用 broker 推回的 `order_status`，不调用任何翻译函数
  - handle_trd_cfm 累计后调 `_infer_order_status` 推断输出码全集 {50, 53, 54, 55, 56}（全是 broker 码）
  - DELETE 端点 cancel-row 起手 sentinel: `status='48'`；DELETE 成功 → `status='54'`（broker CANCELED）；DELETE 失败 → `status='57'`（broker JUNK）
- **v10 schema 调整**（`rpc-field-alignment-ts-unify` 实施）：
  - `order_time` 字段类型 `String(8)` → `String(23)`，格式 `"YYYY-MM-DD HH:MM:SS.fff"`
  - 写入时由 `parse_broker_ts(broker_order_time, order.trd_date, tz='local')` 统一转换（兼容 broker 多种输入格式：`"HH:MM:SS"` / `"HHMMSS"` / `"YYYYMMDDHHMMSS"` / `"YYYYMMDDHHMMSSfff"` 等）
  - 创建 Order 时（`api/orders/place.py`）使用 `format_ts(tz='local')` 生成当前时间字符串
  - DB 迁移脚本：`UPDATE orders SET order_time = trd_date || ' ' || order_time || '.000' WHERE length(order_time) = 8`（把已有 8 字符补齐为 23 字符）
- **v9 schema 调整**：
  - 新增 `order_flag` 字段：`0`=正常委托，`1`=撤单委托占位行（DELETE 端点 INSERT，由 DELETE 端点全权管理 status；broker `ord_cfm` 永远不会 match 到 cancel-row——broker 推 `remark` 永远是原委托 order_no，不是新 cancel-row 的 order_no）
  - cancel-row 字段填充：`stock_code/order_type/price_type/price` 镜像原委托；`volume=0`；`status` 起步 `48`（broker UNREPORTED 本地 sentinel），RPC 成功 → `54`（broker CANCELED 已撤），RPC 失败 → `57`（broker JUNK 废单）
  - DB 迁移脚本：`ALTER TABLE orders ADD COLUMN order_flag INTEGER NOT NULL DEFAULT 0`
- **v8 schema 调整**：
  - 新增 `cancelled_volume` 字段：累计撤单量，broker ord_cfm 推送 `cancelled_volume` / `cancel_volume` / `withdrawn_volume` 任一字段名时累加（兼容多版本）
  - 状态推断规则改：`cancelled_volume >= volume` → 53（已撤）；`cancelled_volume > 0 && traded_volume > 0` → 56（部成部撤）；`cancelled_volume > 0` → 53
  - DB 迁移脚本：`ALTER TABLE orders ADD COLUMN cancelled_volume INTEGER NOT NULL DEFAULT 0`
- **v7 schema 调整动机**：
  - `client_order_id` UNIQUE 约束无法用 — order_id 下单时为空，对应 broker 约束才能稳定
  - `user_def` 是纯透传字段（前端可写可读），不参与任何 DB 约束
  - `order_no` 本身就是 8 位唯一序号，下单流程幂等靠 RPC 客户端 `client_order_id` 透传 + 后端落表前查重（应用层去重）
- **v13 schema 调整**（`layered-architecture-and-strategy-master` 实施）：
  - 新增 `raw_id` 字段：`String(8)`，nullable，**无 default**
  - **仅 DELETE 端点 INSERT cancel-row 时写入**：`raw_id = orig.order_no`；place 端点 INSERT 普通行时 `raw_id = NULL`；broker `ord_cfm` 不写 `raw_id`（broker 不知道这个本地概念）
  - **`raw_id` 与 `order_id` 区别**：`order_id = broker 真实柜台号`（ord_cfm 到达时写入）；`raw_id = 本地 order_no`（cancel-row 指向父单）；两者语义完全不同
  - **`raw_id` 与 `user_def` 关系**：cancel-row 写入后**两者并存**：
    - `user_def = f"CANCEL:{orig.order_no}"`（v9 约定，远程 v9 audit 兼容）
    - `raw_id = orig.order_no`（v13 新增，结构化关联，避免 user_def 字符串解析）
  - **不新增** `raw_id` 索引（cancel-row query 走 `WHERE trd_date=? AND order_no=?` 已有 PK 覆盖）
  - **不动** `ix_orders_user_def`（远程 `2026-07-05-strategy_trade` 已加）
  - DB 迁移脚本：`server/migrations/2026-07-06-add-orders-raw-id.py`（idempotent `ALTER TABLE orders ADD COLUMN raw_id VARCHAR(8)`；列存在则 skip；不强制回填）

### v11 Requirements: orders.status 字典与历史 backfill

#### Requirement: orders.status 字段语义（v11 broker 字典对齐）

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

#### Requirement: orders.status TERMINAL_STATUSES 集合（v11 broker 终态口径）

`server/services/order_status.py:TERMINAL_STATUSES` MUST 等于 `('52','53','54','55','56','57')`（broker xtconstant 终态口径）。

#### Scenario: TERMINAL_STATUSES 含 broker 52

- **WHEN** _infer_order_status 检查 current 是否为终态
- **THEN** broker 52（部成待撤）也算终态, 不会被 trd_cfm 累计覆盖
- **AND** 旧本地 `('51','52','53','54','55','56')` 集合作废, 51（broker 已报待撤）不再算终态

#### Scenario: Status.is_cancellable 含 broker 50

- **WHEN** 业务检查订单是否可撤
- **THEN** Status.is_cancellable 触发码 `('48','49','50')`（含 broker 50=已报也可撤）

#### Requirement: orders.status 历史 DB backfill（v11 一次性）

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
| `amount` | Float | NO | 0.0 | **成交额 = price × volume（change `system-delegation-price-fill-calc` 起本地算，不采用 broker 推送的 `traded_amount`）** |
| `trade_time` | String(23) | NO | "" | **v10 改**：`"YYYY-MM-DD HH:MM:SS.fff"` 完整日期时间（含毫秒） |
| `trade_type` | Integer | NO | 0 | **v9 新增**：`0`=正常成交，`1`=撤单成交（DELETE 端点撤单成功时同步生成，volume=剩余可撤；不参与 buy/sell 统计） |
| `created_at` | DateTime | NO | utcnow | DB 写入时间 |

**Index**:
- `ix_trades_order_no(order_no)` — **v7 重命名**（原 `ix_trades_order(order_id)` 改为按本地 order_no 查）
- `ix_trades_trd_stock(trd_date, stock_code)` — 按股票查当日

**业务规则**:
- 幂等键 `(trd_date, trade_id)`；重复推送不重复插入
- trade_id 缺失时 fallback `f"{order_no}-{trade_time}"`
- trd_date 缺失时用 `_get_active_trd_date(db)`
- **v10 schema 调整**（`rpc-field-alignment-ts-unify` 实施）：
  - `trade_time` 字段类型 `String(8)` → `String(23)`，格式 `"YYYY-MM-DD HH:MM:SS.fff"`
  - 写入时由 `parse_broker_ts(broker_traded_time, trade.trd_date, tz='local')` 统一转换
  - DB 迁移脚本：`UPDATE trades SET trade_time = trd_date || ' ' || trade_time || '.000' WHERE length(trade_time) = 8`
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
| `last_vol` | Integer | NO | 0 | **期初持仓**（仅 do_reconcile 写入） |
| `avl_vol` | Integer | NO | 0 | **可用**持仓（do_reconcile 写入 + manual 调平） |
| `vol` | Integer | NO | 0 | **总持仓**（do_reconcile 写入 + trd_cfm 增量 + manual 调平） |
| `cost_price` | Float | NO | 0.0 | 持仓成本价（仅 do_reconcile 写入） |
| `synced_at` | DateTime | NO | utcnow | 最近同步时间 |
| `synced_from` | String(16) | NO | "" | `rpc_full` (do_reconcile) / `push_partial` (trd_cfm 增量) / `manual` (admin 调平) |

**业务规则**:
- `vol` 的数据源：
  - do_reconcile（day-init 全表覆盖）→ 写入 `avl_vol` + `vol` + `cost_price` + `last_vol`
  - trd_cfm push handler（intra-day 增量）→ 仅 `vol ±= volume`（不影响 avl_vol / last_vol / cost_price）
  - manual adjust API（admin 调平）→ 直接对 `vol` 和/或 `avl_vol` 做原子 +=
- `last_vol` / `cost_price` **只能由 do_reconcile 设置**；其他写入源均不动
- **已删字段**（v12）：`today_buy` / `today_sell` 在 v5 schema 引入以来从未被消费（`do_reconcile` 写入但前端从未读、push handler 不增量），变死字段后删除。**当日买卖累计语义**改由 `Trade` 表 `order_type` + `trd_date` SUM 聚合代替（见 `t0_stats.py` 接口）。
- `market_value` 不存；前端用 `quote.last_price * vol` 实时算
- `synced_from` 含义：`rpc_full` 表示对账权威值，`push_partial` 表示 push 增量后的中间态，`manual` 表示 admin 在盘中手工调平（再次 do_reconcile 会重置为 `rpc_full`）
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
| `diffs_json` | LONGTEXT | NO | "[]" | 差异明细 JSON |
| `broker_asset_json` | LONGTEXT | NO | "" | 柜台资金快照 |
| `local_asset_json` | LONGTEXT | NO | "" | 本地资金快照 |
| `broker_positions_json` | LONGTEXT | NO | "" | 柜台持仓快照 |
| `local_positions_json` | LONGTEXT | NO | "" | 本地持仓快照（init 全量快照可达数百 KB） |
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
## Requirements
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



---

# v18 Sync (change `2026-07-08-t0-task-management`)

> 2026-07-08 sync — 完整 spec delta 段已落库, 详见 archive change。

## ADDED Requirements

### Requirement: 12. `t0_tasks` 表（v18 新增）

**PK**: `id`（自增 int）

**业务定位**：T0 做 T 任务实体。一份 task = 一只券 + 一个底仓 + 一个目标开仓量 + 一个生命周期（active / closed / archived）。

**单行**：否（一用户多任务；一用户一对多）。

| 字段 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| `id` | Integer PK autoincrement | NO | — | 主键 |
| `user_id` | Integer FK→users.id | NO | — | owner；与 users 表级联 NOT enforced（手动控） |
| `stock_code` | String(16) | NO | — | 股票代码（不带 `.SH`/`.SZ` 后缀冗余，按既有约定带后缀） |
| `base_volume` | Integer | NO | 0 | 底仓量（"保留部分底仓"语义，>0 时不平到 0） |
| `target_volume` | Integer | NO | 0 | 目标开仓量（区别于现仓位；可为负=净减仓目标） |
| `coefficient` | Float | NO | 1.0 | 配平系数（沿用 REQ-TRADE-005 语义） |
| `status` | Enum('active','closed','archived') | NO | 'active' | 生命周期 |
| `note` | String(255) | YES | NULL | 用户备注 |
| `created_trd_date` | String(8) | NO | — | 创建时所属交易日（业务字段，不用 created_at 倒推） |
| `created_at` | DateTime | NO | now() | 创建时间 |
| `closed_at` | DateTime | YES | NULL | 关任务时间 |

**索引**：
- PK(id)
- INDEX(stock_code) — 按股票过滤
- INDEX(status, created_at) — 列表按状态 + 时间排序
- INDEX(user_id, status) — 按用户权限过滤

**与其他表关系**：
- `orders.task_id` → `t0_tasks.id`（nullable FK；不强制外键约束以保留历史 user_def='T0' 单的兼容）
- 不级联删除：删 task 时仅置 orders.task_id = NULL（保留审计）

#### Scenario: 建表迁移幂等

- **WHEN** migration `add-t0-tasks.py` 跑
- **THEN** `CREATE TABLE IF NOT EXISTS t0_tasks (...)` 幂等
- **AND** `CREATE INDEX IF NOT EXISTS ix_t0_tasks_stock_code ON t0_tasks(stock_code)`
- **AND** `CREATE INDEX IF NOT EXISTS ix_t0_tasks_status_created ON t0_tasks(status, created_at)`
- **AND** `CREATE INDEX IF NOT EXISTS ix_t0_tasks_user_status ON t0_tasks(user_id, status)`
- **AND** MySQL：`CREATE TABLE IF NOT EXISTS ... ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci`
- **AND** SQLite：`CREATE TABLE IF NOT EXISTS ... `（SQLite 兼容模式用 text 类型替代 enum）

#### Scenario: SQLAlchemy ORM 定义

```python
class T0Task(Base):
    __tablename__ = "t0_tasks"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False)
    stock_code = Column(String(16), nullable=False)
    base_volume = Column(Integer, nullable=False, default=0)
    target_volume = Column(Integer, nullable=False, default=0)
    coefficient = Column(Float, nullable=False, default=1.0)
    status = Column(Enum("active", "closed", "archived"), nullable=False, default="active")
    note = Column(String(255), nullable=True)
    created_trd_date = Column(String(8), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    closed_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_t0_tasks_stock_code", "stock_code"),
        Index("ix_t0_tasks_status_created", "status", "created_at"),
        Index("ix_t0_tasks_user_status", "user_id", "status"),
    )
```

### Requirement: 13. `orders.task_id` 列新增（v18 新增）

**业务定位**：委托关联 T0 任务（可空）。

| 字段 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| `task_id` | Integer | YES | NULL | 关联 `t0_tasks.id`（nullable FK） |

**迁移策略**：
- `ALTER TABLE orders ADD COLUMN task_id INT NULL` 幂等
- `CREATE INDEX IF NOT EXISTS ix_orders_task_id ON orders(task_id)` 幂等
- **不回填**：历史 user_def='T0' 单保持 `task_id = NULL`，继续走 REQ-TRADE-006 聚合路径

**与 user_def 关系**：
- task 下单：`user_def = 'T0'` AND `task_id = <id>`
- 旧 T0 单（无 task）：`user_def = 'T0'` AND `task_id = NULL`
- 普通单（非 T0）：`user_def = ''` AND `task_id = NULL`

#### Scenario: migration 幂等检测列存在

- **WHEN** migration 跑
- **THEN** 先查 `INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME='orders' AND COLUMN_NAME='task_id'`
- **AND** 已存在则跳过 ALTER；不存在则 ADD
- **AND** SQLite 用 `PRAGMA table_info(orders)` 检测

#### Scenario: task_id NULL 行为

- **WHEN** Order.task_id = NULL
- **THEN** `services/t0/tasks.py::aggregate_task_stats(task_id)` 仍可访问（不报 FK 错）
- **AND** `aggregate_by_stock(..., user_def='T0')` 兼容 NULL（保持现状）

### §13. `stocks` — 股票基础信息表（v23 slim-stocks-table）

**业务定位**:股票核心信息(代码/名称/板块) + 交易粒度配置(回转标志/最小买入数量/买卖单位)。从东方财富 API 抓取基础信息,admin 通过 `/admin/stock-config` 编辑交易粒度。前端在 `/admin/stock-config` 页面消费。

**PK**: `stock_code VARCHAR(16)`(带 `.SH/.SZ` 后缀,与 `quote_snapshots` 一致)

**字段精简历史**:
- v21 (2026-07-10) stock-info-crawler: 14 个业务字段(基础信息 + 公司简介)
- **v23 (2026-07-12) slim-stocks-table: 6 个业务字段**(代码/名称/板块 + 3 个交易粒度),9 字段已删除,历史数据保留在 `stocks_legacy` 表

| 字段 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| `stock_code` | VARCHAR(16) | NO | — | 股票代码(PK,如 `000001.SZ`) |
| `stock_name` | VARCHAR(64) | NO | "" | 股票名(如 `平安银行`) |
| `sector` | VARCHAR(64) | YES | NULL | 板块(申万二级,如 `银行-国有大型银行`) |
| `is_t0_able` | TINYINT(1) | NO | `0` | 回转标志 (FALSE=T+1 / TRUE=T+0) |
| `min_buy_qty` | INT | NO | `100` | 最小买入数量(A 股默认 100 股) |
| `trade_unit` | INT | NO | `1` | 买卖单位(序号无业务意义,默认 1) |
| `created_at` | DATETIME | NO | `CURRENT_TIMESTAMP` | 创建时间 |
| `updated_at` | DATETIME | NO | `CURRENT_TIMESTAMP` | 更新时间(自动 ON UPDATE) |

**已删除字段**(v21 → v23):
- ~~`industry`~~ 行业 — 前端未消费
- ~~`market`~~ 市场 — 从 `stock_code` 后缀派生
- ~~`list_date`~~ 上市日期 — UI 未展示
- ~~`total_share` / `float_share`~~ 股本 — UI 未展示
- ~~`market_cap` / `pe_ratio` / `pb_ratio`~~ 估值 — UI 未展示
- ~~`intro`~~ 公司简介 — UI 未展示

**索引**:无(`sector` 暂未加索引,数据量小走全表扫)

**upsert 策略**(REQ-STOCK-002):
- 已存在 + `updated_at > NOW() - 7 DAY` → 跳过(`skipped`)
- 已存在 + `updated_at <= NOW() - 7 DAY` → 覆盖 crawler 写入的字段(`updated`)
- 不存在 → INSERT(`inserted`)
- crawler 入仓字段:stock_name + sector
- admin 编辑字段:stock_name + sector + is_t0_able + min_buy_qty + trade_unit

**DDL 幂等**:`CREATE TABLE IF NOT EXISTS stocks` 重复
跑安全;`ALTER TABLE stocks ADD/DROP COLUMN` 通过 INFORMATION_SCHEMA 探测后执行(v23 迁移脚本策略)。

**历史数据保留**:stocks_legacy 表存 14 字段完整快照,v23 迁移时一次性 CREATE TABLE AS SELECT 拷贝,不再被业务代码访问(仅供紧急查询/审计)。

#### Scenario: 增量 upsert - 7 天内跳过

- **GIVEN** stocks 表已有 `stock_code='000001.SZ'` 行,`updated_at` = 当前时刻
- **WHEN** `repo.stocks.upsert(db, '000001.SZ', new_data)`
- **THEN** 返 `'skipped'`,DB 不变

#### Scenario: 增量 upsert - 7 天外覆盖

- **GIVEN** stocks 表已有 `stock_code='000001.SZ'` 行,`updated_at` = 8 天前
- **WHEN** `repo.stocks.upsert(db, '000001.SZ', new_data)`
- **THEN** 返 `'updated'`,crawler 字段(stock_name + sector)被覆盖,`updated_at` 自动刷新
- **AND** `is_t0_able` / `min_buy_qty` / `trade_unit` **不**被覆盖(仅 admin 编辑入口可改)

#### Scenario: 增量 upsert - 新行插入

- **GIVEN** stocks 表无 `stock_code='999999.SZ'` 行
- **WHEN** `repo.stocks.upsert(db, '999999.SZ', new_data)`
- **THEN** 返 `'inserted'`,新行写入,`is_t0_able=0` / `min_buy_qty=100` / `trade_unit=1` 取默认值,`created_at` 和 `updated_at` 自动设当前时间

#### Scenario: admin 编辑 stocks 字段白名单

- **GIVEN** admin 调用 `PATCH /api/stocks/{code}` with body `{stock_name, sector, is_t0_able, min_buy_qty, trade_unit}`
- **WHEN** 请求处理
- **THEN** 5 字段全部可被覆盖(其他字段如 `industry` 返 422 拒绝)
- **AND** 返回更新后的完整 stock 对象(6 字段)

## ADDED Requirements

### Requirement: 14. `orders.strategy_type` 列新增（v66 新增）

**业务定位**：委托策略类型（强约束枚举，区分下单来源）。

| 字段 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| `strategy_type` | TINYINT | NO | 0 | 0=普通单(Trade.vue OrderForm 下单) 1=快速做T(T0Trade.vue 智能做T下单) 2=策略下单(v126 母单路径signal_consumer归因) |

**迁移策略**:
- `ALTER TABLE orders ADD COLUMN strategy_type TINYINT NOT NULL DEFAULT 0` 幂等
- `CREATE INDEX ix_orders_strategy_type ON orders(strategy_type)` 幂等（MySQL 8 不支持 IF NOT EXISTS, 通过 INFORMATION_SCHEMA.STATISTICS 探测跳过）
- **不回填**: 历史 user_def='T0' 单保持 `strategy_type = 0`, 继续走 user_def 字符串聚合路径（向后兼容）

**与 user_def 关系**:
- Trade.vue OrderForm 下单（普通单）: `user_def = ''` AND `strategy_type = 0`
- T0Trade.vue 智能做T下单（v66 NEW）: `user_def = 'T0'` AND `strategy_type = 1`
- 历史 T0 单（无显式 strategy_type）: `user_def = 'T0'` AND `strategy_type = 0`（DEFAULT 兜底）
- 策略下单母单路径（v126 NEW）: `user_def = <strategy_name>` AND `task_id = <parent_task_id>` AND `strategy_type = 2`

**与 task_id 关系**:
- task 下单（v18 行为）: `user_def = 'T0'` AND `task_id = <id>` AND `strategy_type = 1`
- 无 task 的 T0 单: `user_def = 'T0'` AND `task_id = NULL` AND `strategy_type = 1`
- 普通单: `user_def = ''` AND `task_id = NULL` AND `strategy_type = 0`
- 策略下单母单（v126 NEW）: `task_id = <母单.task_id>` AND `strategy_type = 2`（母单路径下, task_id 必带, 缺则 INVALID_PARENT_TASK）

#### Scenario: migration 幂等检测列存在

- **WHEN** migration 跑
- **THEN** 先查 `INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME='orders' AND COLUMN_NAME='strategy_type'`
- **AND** 已存在则跳过 ALTER；不存在则 ADD COLUMN
- **AND** 通过 inspect(engine).get_columns('orders') 探测（业务库 + 业务账号验证）

#### Scenario: migration 幂等检测索引存在

- **WHEN** 创建索引
- **THEN** 先查 `INFORMATION_SCHEMA.STATISTICS WHERE TABLE_NAME='orders' AND INDEX_NAME='ix_orders_strategy_type'`
- **AND** 已存在则跳过 CREATE INDEX；不存在则 CREATE INDEX

#### Scenario: 撤单行 strategy_type 继承原单

- **WHEN** 撤单本地代理创建 cancel-row (order_flag=1)
- **THEN** cancel-row 的 strategy_type 字段自动 = 原委托 strategy_type（SQLAlchemy ORM 复制，不显式设 strategy_type）
- **AND** 分类语义保留：原普通单撤单 → strategy_type=0 cancel-row；原做T单撤单 → strategy_type=1 cancel-row

#### Scenario: Pydantic Literal 强约束

- **WHEN** 客户端 POST `/api/orders/place` payload
- **THEN** `PlaceOrderRequest.strategy_type` 必须 = 0 或 1
- **AND** 传 2 / -1 / "1"（字符串）→ 422 ValidationError
- **AND** 不传 → 默认 0（与 ORM DEFAULT 0 对齐）

---

## Schema Governance (v130+, 防止 dev/prod 脱节)

### 三个事实源 + 各自角色

| 角色 | 路径 | 谁改 | 同步方向 |
|---|---|---|---|
| **dev 库** `evtrade_dev` | MySQL `192.168.10.2:33066/evtrade_dev` | 开发者日常改 | → yml (export) |
| **`server/schema.yml`** | 仓库内, 18 张表 + 索引 + 注释 | PR review 改 | → DB (apply) |
| **prod 库** `evtrade` | MySQL `192.168.10.2:33066/evtrade` | **永远不直接改** | ← yml (apply) |

### 日常流程

```bash
# 1. dev 库改了表结构 (手 ALTER 或跑 migration)
mysql -h ... -e "ALTER TABLE strategy ADD COLUMN foo INT"

# 2. 拉一份最新到 yml (这是 dev 库 → 仓库的"提交")
python scripts/sync_schema.py export --source-url "$EVTRADE_DEV_URL"
# 或: source .env.dev && python scripts/sync_schema.py export

# 3. 提交 yml 改到 git
git diff server/schema.yml   # 审查
git add server/schema.yml && git commit -m "schema: add strategy.foo"

# 4. (其他人 / CI) prod 库自动跟上
python scripts/sync_schema_to_target.py   # dev → prod 一次到位
# 或: 在每台跑 backend 的机器上, backend 启动前会自动 apply (见 evctl.py:_pre_schema_check)
```

### 三套工具, 各司其职

| 工具 | 何时用 | 行为 |
|---|---|---|
| `sync_schema.py export` | dev 库改了 → 把表结构写进 yml 提交 | DB → yml |
| `sync_schema.py diff` | 任何时候检查 yml ↔ 实际库 drift | 只读 |
| `sync_schema.py apply` | yml 改了 → 推 DB (启动 backend 时自动跑) | yml → DB (只 ADD / CREATE / MODIFY, **绝不 DROP**) |
| `sync_schema.py apply --strict` | CI / 验收, 任何 drift 拒绝 | apply 失败 = 拒绝 |
| `sync_schema_to_target.py` | 一次性把 dev 库全量同步到 prod 库 | export(diff→yml) → apply |
| `server/migrations/*.py` | **历史包袱**, 33 个手写 ad-hoc 迁移, 各自幂等 | 一次性, 跑过的就 skip (但 `_applied_migrations` 表只供人看, 实际靠幂等) |

### 自动启动预检 (v130+)

`scripts/evctl.py` 启动 backend 时, **在 spawn uvicorn 之前**自动跑 `sync_schema.py apply`:
- apply 失败 → 启动失败, 打印完整 stderr
- 逃生口: `EVTRADE_SKIP_SCHEMA_CHECK=1 python scripts/evctl.py start backend`

### 推荐 cron (可选)

```bash
# 每天凌晨跑一次 dev→prod 同步, 任何 drift 一票否决
0 3 * * *  cd /root/workspcae/codespace/EvTrade && \
  /root/workspcae/codespace/EvTrade/.venv/bin/python \
  scripts/sync_schema_to_target.py --strict \
  >> /var/log/evtrade_schema_sync.log 2>&1
```

### 反模式 (禁止)

- ❌ 直接 ALTER prod 库 (`mysql -h prod ... -e "ALTER ..."`) — 绕过 yml, 必脱节
- ❌ 只改 yml 不跑 export (yml 会跟 dev 库脱节)
- ❌ 跑 `sync_schema.py apply` 加 DROP / TRUNCATE — 当前 apply 不支持, 是 feature 不是 bug (防呆)
- ❌ 删了 yml 里的表 / 列但 prod 库还有 — 这是"真脱节", 需要手写 migration 配合

### 已知遗留 (后续可优化)

- 33 个 ad-hoc migration 跟 sync_schema 体系并存, 偶尔会有 `_applied_migrations` 记录"跑过"但实际未生效 (幂等 bug). 直接重跑 migration 通常能补.
- 长期可考虑: 把 ad-hoc migration 整合成 alembic autogenerate baseline (见方案 3, 待评估).
