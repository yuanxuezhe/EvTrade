# RPC 字段对齐 + 时间戳统一

## 1. Why

逐字段比对 `iquant/xtquant_api.py`（柜台/msgpacket 协议事实源）与 `server/` 当前实现，发现两类系统性问题：

### 1.1 RPC 字段不匹配

`xtquant_api.py` 是 msgpacket 协议的**事实源**（柜台 broker 与 server 间的字段约定），
但 server 端在解析响应和落库时**没有严格遵循**，导致：

| 路径 | xtquant 字段 | server 当前处理 | 问题 |
|---|---|---|---|
| `qry_pos` | `stock_code, last_vol, volume, avl_amt, avg_price, market_value` | `_parse_positions` 接收 `avl_amt` / `avg_price` 但**重命名**为 `available` / `cost` | 字段名漂移；reconcile 写库时还要回退读 `available`/`cost`/`avl_vol`/`vol` 多种别名 |
| `qry_pos` | `market_value` | 直接读 broker 字段 | ✓ OK |
| `qry_ord` | `order_id, stock_code, order_type, price_type, price, order_volume, traded_volume, traded_price, order_status, status_msg, strategy_name, order_remark, order_time` | `_parse_orders` 将 `order_status` 重命名为 `status`、丢弃 `strategy_name` / `status_msg` | 内部命名漂移；status 字段语义对外不一致 |
| `qry_mch` | `order_id, traded_id, stock_code, order_type, traded_volume, traded_price, traded_amount, strategy_name, order_remark, traded_time` | `_parse_trades` 将 `traded_id`→`trade_id`、`traded_time`→`trade_time`、`traded_volume`→`volume`、`traded_price`→`price`，**丢弃** `traded_amount`/`strategy_name`/`order_remark` | 4 处重命名 + 3 字段丢失 |
| `qry_ast` | `account_id, cash, frozen_cash, market_value, total_asset` | `_parse_asset` **丢弃** `account_id` | 缺字段（虽不致命，但与协议不对齐） |
| push `ord_cfm` | `order_id, stock_code, order_status, order_volume, traded_volume, price, traded_price, strategy_name, remark, order_time` | `handle_ord_cfm` 读 `order_id`/`remark`/`status`/`status_msg`/`cancelled_volume`，**丢弃** `order_time`/`strategy_name`/`order_volume` | ord_cfm 时间不入库，对账/排序需另查 |
| push `trd_cfm` | `traded_id, stock_code, traded_volume, traded_price, account_id, strategy_name, remark` | `handle_trd_cfm` 接受 `trade_id`/`order_id`/`remark`/`stock_code`/`order_type`/`price`/`volume`/`amount`/`trade_time` | 与 qry_mch 同问题（`trade_id` vs `traded_id`、`price` vs `traded_price`）；xtquant 推 `traded_*` 但 server 读非 `traded_*` 字段名（兼容路径但易错） |
| push `pos_cfm` | `stock_code, last_vol, volume, avl_amt, avg_price, market_value` | `handle_pos_cfm` 读 `volume`/`available`/`cost_price`/`market_value` | 缺 `avl_amt` 字段名支持（broker 实际推 `avl_amt`，落库时 `row.available` 读不到） |
| push `ast_cfm` | `account_id, cash, frozen_cash, market_value, total_asset` | `handle_ast_cfm` 读 `total_asset`/`cash`/`frozen`/`market_value` | 协议是 `frozen_cash`，但代码读 `frozen` 优先（虽然有 `frozen_cash` 兜底但次序不对） |

**根因**：分阶段重构（v5 schema-refactor、v6 order-pk-by-orderno、v7 user_def、v8 cancelled-volume、v9 cancel-row 隔离）每次只动局部，parsers / push handlers / reconcile 各自为政，缺乏 single source of truth 引用 `xtquant_api.py`。

### 1.2 时间戳格式不统一

| 位置 | 当前格式 | 问题 |
|---|---|---|
| `Order.order_time` ORM 列 | `String(8)` 存 `"HH:MM:SS"` | 与 xtquant broker 实际推送的 `order_time`（"HH:MM:SS"）一致，但**无日期无毫秒**，无法确定跨日委托归属 |
| `Trade.trade_time` ORM 列 | `String(8)` 存 `"HH:MM:SS"` | 同上 |
| `Order` 创建时（`order_place.py:89`） | `datetime.now().isoformat(timespec='seconds')` → `"2026-06-25T10:00:00"` | ISO 8601 带 T，与 xtquant 协议字段 `order_time`（"HH:MM:SS"）不同格式 |
| WS broadcast ts（`_broadcast_ord_cfm`、`_listen_pushs`） | `isoformat(timespec='seconds')` → `"2026-06-25T10:00:00"` | ISO 带 T，与 order_time/trade_time 不一致 |
| `pos_cfm` / `ast_cfm` 的 `synced_at` / `pushed_at` / `created_at` | `DateTime` 类型 | DB 内是 datetime，但 API 响应需 `isoformat()`，无统一字符串格式 |
| xtquant 应答包 `timestamp` | `datetime.now().strftime('%Y%m%d%H%M%S%f')[:-3]` → `"20260625100000123"` | 14位紧凑串 + 毫秒；与 server 端 4 处时间格式都不一致 |

**用户要求**：表格（API 响应）里时间戳全部统一为字符串，格式 `2026-06-24 17:56:28.281`（23 字符：`YYYY-MM-DD HH:MM:SS.fff`）。

## 2. What

### 2.1 RPC 字段对齐（commit 1 + 2）

**原则**：
- 解析层（`_parse_*`）**保留 broker 原始字段名**（snake_case，`traded_id`/`avl_amt`/`avg_price` 等），不再重命名
- API/DB 层通过 Pydantic / ORM 做内部命名映射（与 schema 演进解耦）
- push handler 直接读 broker 字段名

**改动文件**（commit 1 — parsers）：
- `server/rpc/parsers_business.py` — 4 个 `_parse_*` 全部使用 broker 原始字段名（详见 tasks.md §1.1）
- `server/rpc/handlers.py` — 透传 `dict`，不下放内部命名
- `server/api/holdings.py` / `asset.py` / `trades.py` / `positions.py` / `order_query.py` 端点：
  - 解析器输出已经是 broker 原字段 → 端点直接转 Pydantic / ORM
  - 移除 `available`/`cost`/`trade_id`/`trade_time`/`volume` 等内部别名
  - 持仓：DB 列 `avl_vol`/`cost_price`/`vol` 保持不变（v5 schema 决策），由端点做 `avl_amt`→`avl_vol` 显式映射

**改动文件**（commit 2 — push handlers）：
- `server/services/push_handler_ord.py` — 读 broker 原字段 `order_status`（不再 alias `status`）、`order_time`、`order_volume`、`strategy_name`
- `server/services/push_handler_trd.py` — 读 broker 原字段 `traded_id`/`traded_volume`/`traded_price`/`traded_amount`/`traded_time`/`account_id`/`strategy_name`
- `server/services/push_handler_pos.py` — 读 broker 原字段 `avl_amt`/`avg_price`
- `server/services/push_handler_ast.py` — 读 broker 原字段 `frozen_cash`/`account_id`/`total_asset`（不再 alias `frozen`）
- `server/services/reconcile.py` — `_apply_broker_data` 同步用 broker 原字段名

### 2.2 时间戳统一（commit 3）

**统一格式**：`"2026-06-24 17:56:28.281"`（23 字符，UTC 或本地由上下文决定）
- 业务时间戳（order_time / trade_time / order 创建时间）—— 用**本地时间**（柜台/QMT 都是本地）
- 系统时间戳（created_at / updated_at / pushed_at / synced_at）—— 用 **UTC**（DB 内部存 UTC datetime，API 响应序列化为 UTC 字符串）

**改动**：

1. **DB schema**（`server/models/orm.py`）：
   - `Order.order_time`: `String(8)` → `String(23)`（`"2026-06-24 17:56:28.281"`）
   - `Trade.trade_time`: `String(8)` → `String(23)`
   - 系统 DateTime 列保持不变（`DateTime` 类型便于索引/查询；序列化层做转换）

2. **工具函数**（`server/services/push_helpers.py`）：
   - 新增 `format_ts(dt=None, *, tz='local') -> str` — 统一时间戳字符串化入口
   - 新增 `parse_broker_ts(s: str, trd_date: str) -> str` — 把 broker 各种格式（"HH:MM:SS" / "HHMMSS" / "YYYYMMDDHHMMSS" / 毫秒紧凑串）解析为标准格式

3. **API 输出层**：
   - `OrderOut` / `Order` schema 序列化时所有 datetime → 标准字符串
   - `AssetOut.synced_at` / `PositionOut.synced_at` → 标准字符串
   - WS broadcast `ts` 字段 → 标准字符串

4. **push handler 写入时**：
   - `Order.order_time`：push 来时把 broker `order_time`（"HH:MM:SS"）按当日 trd_date + UTC→local 转为标准格式
   - `Trade.trade_time`：同上
   - `Order.status` 创建（`order_place.py:89`）→ 改用 `format_ts()`

5. **xtquant 应答包**：
   - 不动（柜台侧，不在 server 范围）

### 2.3 测试更新（commit 4）

- `test_push_handlers.py`：所有 `ts="20260614 09:30:00"` / `"x"` 改为 `ts="2026-06-14 09:30:00.000"`
- `test_push_handlers.py`：ord_cfm / trd_cfm 测试用 broker 原字段名（`order_status` 而非 `status`、`traded_id` 而非 `trade_id` 等）
- `test_push_listener.py`：注入的 fake_row 字段名同步
- `test_orders_api.py`：若涉及 `order_time` / `status` 字段断言需更新
- 新增 `test_format_ts.py`：覆盖 `format_ts()` / `parse_broker_ts()` 各种输入

## 3. 影响面

**后端（server/）**：
- `rpc/parsers_business.py` — 重构 4 个解析器（commit 1）
- `services/push_handler_*.py` — 4 个 handler 字段名（commit 2）
- `services/reconcile.py` — `_apply_broker_data` 字段名（commit 2）
- `services/push_helpers.py` — 加 `format_ts` / `parse_broker_ts`（commit 3）
- `models/orm.py` — `Order.order_time` / `Trade.trade_time` 改 `String(23)`（commit 3，需 DB migrate 或 drop_all 重 init）
- `api/order_query.py` / `order_place.py` / `api/_order_schemas.py` — 字段映射 + ts 字符串化（commit 3）
- `api/asset.py` / `api/positions.py` / `api/trades.py` / `api/holdings.py` — synced_at 字符串化（commit 3）
- `rpc/transport.py` — WS broadcast `ts` 改用 `format_ts()`（commit 3）
- `services/push_handler_*.py` — `created_at` / `updated_at` / `synced_at` / `pushed_at` 落库仍是 datetime，序列化时再转字符串（commit 3）
- 测试 4 个文件（commit 4）

**前端（client/）**：
- `holdings.applyOrderPush` / `applyTradePush` / `applyAssetPush`：`status` 字段名变 `order_status`（commit 2 影响）
- 表格 `order_time` / `trade_time` 显示：从 8 字符变 23 字符（commit 3 影响）
- WS payload `ts` 字段：格式从 ISO 8601 变 `2026-06-24 17:56:28.281`（commit 3 影响）

**数据迁移**：
- DB 已有 `Order.order_time` / `Trade.trade_time` 列宽 8 → 23，SQLite 支持（无强约束）
- 已存 8 字符数据需要回填日期前缀：`<trd_date> <order_time>` → 拼接成 23 字符
- 简单方案：本次同步 `Base.metadata.drop_all` + `init_db()`，丢掉测试数据；生产部署需在 PR 中说明迁移 SQL

## 4. Spec Deltas

详见 `spec-deltas/`：
- `rpc-protocol/spec.md`：补 §X 「字段名约定（broker 原字段名 vs server 内部命名）」
- `data-model/spec.md`：补 §Y 「时间戳列格式」（`order_time`/`trade_time` 23 字符规则）
- `push-handler/spec.md`：补 §Z 「push handler 字段映射表」（`ord_cfm`/`trd_cfm`/`pos_cfm`/`ast_cfm` 字段一一对应 xtquant 协议）

## 5. 不在本 change 范围

- xtquant broker 自身代码（`iquant/xtquant_api.py`）
- msgpacket 协议本身
- 前端 store/视图层代码（前端改动不在本仓；需要另一份 `client/field-alignment` 提案追踪）

## 6. Tasks

见 `tasks.md`。
