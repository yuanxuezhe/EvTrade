# Schema说明

## 对应代码路径

- `server/schema.yml`（1016 行，数据库结构单一真相源）
- `server/tables/*.py`（gen_tables.py 生成的表访问类，一表一文件）
- `scripts/sync_schema.py` / `scripts/gen_tables.py`（同步与生成工具，详见《脚本工具/数据库迁移与Schema》）
- `openspec/specs/data-model/spec.md`（能力级 spec）

## 功能概述

EvTrade 全部 21 张业务表的结构说明：表名、主键、关键列、用途；以及加表/改字段的完整操作步骤。MySQL（utf8mb4/InnoDB），schema 以 `server/schema.yml` 为权威，代码访问层为 `server/tables/` 动态 ORM。

## 文件清单（全部表，按 schema.yml 顺序）

| 表名 | 主键 | 关键列 | 用途 |
|------|------|--------|------|
| `_applied_migrations` | `name` | `applied_at` | server/migrations 已应用记录 |
| `assets` | `id` | `cash/available/frozen_cash/market_value/total_asset/last_asset/synced_at/synced_from` | 资金账户快照（单行，柜台同步） |
| `order_no_seq` | `seq_name` | `last_value/updated_at` | 订单号序列（原子 UPSERT 取号，多 generator） |
| `orders` | `trd_date, order_no` | `order_id/user_def/stock_code/order_type/price_type/price/volume/traded_volume/avg_price/status/task_id/strategy_type` | 当日委托单；6 个二级索引（trd_status/task_id/stock/order_id/user_def/strategy_type） |
| `positions` | `stock_code` | `stock_name/last_vol/avl_vol/vol/cost_price/synced_at` | 持仓（每股票一行） |
| `quote_snapshots` | `id`（自增） | `stock_code/last_price/open/high/low/prev_close/volume/amount/bid1-5_price_vol/ask1-5_price_vol/ts` | 行情快照落库（quote_cache 周期 flush）；索引 ts、(stock_code,ts) |
| `reconcile_report` | `trd_date, mode, created_at` | `diffs_json/broker_asset_json/local_asset_json/broker_positions_json/local_positions_json/rpc_status` | 日初对账报告（LargeText 存 JSON） |
| `stkpool` | `id`（自增） | `name/remark/created_at` | 证券池主表 |
| `stkpooldetail` | `id, stock_code` | （仅 PK 两列）；索引 id | 证券池明细（share PK id + stock_code） |
| `stocks` | `stock_code` | `stock_name/sector/is_t0_able/min_buy_qty/trade_unit/short_name/stktype/scale` | 全 A 股基础信息（爬虫同步） |
| `strategy` | `strategy_id`（自增） | `user_id/script_id/name/status/is_public/stock_code/best_params(JSON)/t0_params(JSON)` | 策略定义；索引 (user_id,script_id) |
| `strategy_order` | `id`（自增） | `task_id/user_id/strategy_id/stock_code/status/active_task_id/run_count` | 策略下单母单（可重复启停，子单按 parent_task_id 归因） |
| `strategy_script` | `user_id, id` | `name/code(LargeText)/params_schema(JSON)/description/status/is_public` | 用户 Python 策略源码 + 参数 schema；索引 (user_id,status) |
| `strategy_script_audit` | `id`（BIGINT 自增） | `task_id/stime/trd_date/phase/trigger_type/stock_code/price/volume/indicators/state/order_no/payload` | 策略执行审计流水（JSON 多列）；索引 (task_id,created_at)、(task_id,trd_date) |
| `strategy_task` | `id`（自增） | `user_id/stock_code/mode/status/params(JSON)/backtest_result(JSON)/pnl/live_signals/progress/execution_service/strategy_id/batch_no/metric/backtest_metric_value/version` | 回测/实盘任务运行态 + 结果；索引 user_status、mode、(strategy_id,batch_no,status) |
| `sys_config` | `user, cfg_key` | `cfg_val/desc/updated_by` | 系统配置 KV |
| `sys_status` | `id` | `trd_date/status/is_half_day/initialized_at/closed_at` | 交易日状态机（open/closed，日初切换） |
| `t0_tasks` | `id`（自增） | `user_id/stock_code/base_volume/target_volume/coefficient/status/created_trd_date` | T0 做T任务；索引 user_status、(status,created_at)、stock_code |
| `token_sessions` | `token_hash` | `user_id/role/created_at/last_seen_at` | JWT 会话缓存（跨 worker 共享，重启即清空）；索引 user、last_seen |
| `trades` | `trd_date, order_no, trade_id` | `stock_code/order_type/price/volume/amount/trade_time/trade_type` | 成交回报；索引 order_no、(trd_date,stock_code) |
| `users` | `id`（自增） | `username/password_hash/email/full_name/role/is_active/must_change_password/last_login_at` | 用户与 RBAC 角色 |

## 核心实现

### 类型体系与关键约定

- yml 类型用 SQLAlchemy 风格名：`String(N)`→VARCHAR、`Integer`→INT、`BIGINT`、`Float`、`TinyInt`、`Boolean`→TINYINT(1)、`Text`、`LargeText`→LONGTEXT、`JSON`、`DateTime`、`SmallInteger`
- `trd_date` 统一 `String(8)`（如 `20260816`）；时间戳列 `created_at/updated_at` 常配 `server_default: CURRENT_TIMESTAMP`
- 大 JSON 一律 `LargeText`（`reconcile_report` 的 4 个 json 列），防 VARCHAR(255) fallback 截断
- 业务主键多为复合键（orders/trades 按 `trd_date+order_no`），`order_no` 为 8 位数字字符串

### 表访问层（server/tables/）

每表一个 `server/tables/<表名>.py`，类名 PascalCase（`t0_tasks→T0Tasks`、`strategy_order→StrategyOrder`）。统一通过 `TableBase` 的 `upsert_one` 写入、`query_one/query_by_fields` 查询；公共 helper（`get_engine/get_conn/transaction/aggregate/scalar_query/exec_sql`）从 `server/tables/__init__.py` 导出。生成文件**禁止手改**。

### 加表完整步骤

1. 在 `server/schema.yml` 的 `tables:` 下新增表块：`pk` + `columns`（每列 type/nullable/default）+ 可选 `indexes`/`comment`
2. `uv run python scripts/sync_schema.py diff` —— 确认只出现 "Tables to ADD: <新表>"
3. `uv run python scripts/sync_schema.py apply` —— 建表并自动重生成 `server/tables/<新表>.py` 与 `__init__.py`
4. 需要初始数据则写 `server/migrations/YYYY-MM-DD-*.py` 迁移或扩展 `scripts/seed_missing_data.py`
5. `git add server/schema.yml server/tables/`，schema 与生成代码**同一 commit**提交
6. 重启 backend：`uv run python scripts/evctl.py restart backend`（启动体检会校验 yml↔DB 一致）

### 加字段完整步骤

1. 在 schema.yml 对应表的 `columns:` 下加列块（新列尽量 `nullable: true` 或带 default，避免大表锁行）
2. `sync_schema.py diff` 预览（应只有 `ADD columns`）
3. `sync_schema.py apply`（ADD COLUMN + 自动重生该表的 tables 代码）
4. 检查重生后的 `server/tables/<表>.py` type hint 与 `__fields__` 是否符合预期
5. 提交 schema.yml + tables 变更；若是 strategy_exec 共享表（`strategy_script`/`strategy_task`/`strategy_script_audit`），同步核对 strategy_exec 侧读写代码

### 改字段类型 / 删列 / 删表

- 改类型：改 yml → `diff` 会报 `type X -> Y` → `apply` 走 `MODIFY COLUMN`；**缩小类型（如 TEXT→VARCHAR）有数据截断风险，先备份**
- 删列/删表：sync_schema 不支持。手写 `server/migrations/YYYY-MM-DD-<动作>.py`（含 `migrate(engine)`，幂等）执行 DDL，再手动同步删 yml 中对应块并重新 `export` 校准，最后重生 tables
- 历史参考：`2026-08-10-drop-legacy-strategy-tables.py`（删表）、`2026-07-12-slim-stocks-table.py`（精简表）

### 与 strategy_exec 的共享单库约定

`strategy_script` / `strategy_task` / `strategy_script_audit` 由 EvTrade 与 strategy_exec 两服务共用同一 `EVTRADE_DB_URL`（见 `openspec/specs/data-model/spec.md`）。改这三张表结构时必须同时检查 `strategy_exec/` 侧的 SQL/ORM 读写。

## 依赖关系

- 上游：`scripts/sync_schema.py`（apply 建结构）、`scripts/gen_tables.py`（生成访问类）、`server/migrations/`（历史变更）
- 下游：backend 全部 API/service 层（经 `server/tables`）、strategy_exec（共享 3 张策略表）、`evctl.py` 启动体检（diff）

## 修改指南

- 一切结构变更以 `server/schema.yml` 为起点，**禁止直接对 DB 手改 DDL 后不回写 yml**（会被启动体检报 drift）
- 生产库变更走"dev 改 → export → commit yml → 手动 apply --strict"流程，禁止 `--strict` 之外静默 reconcile
- 加索引命名沿用 `ix_<表>_<列语义>` 约定；唯一索引 yml 不表达（只能迁移脚本建），新唯一约束写 migration
- 新表若被 push_handlers/查询热路径使用，注意补二级索引（参考 orders 的 6 索引布局）
