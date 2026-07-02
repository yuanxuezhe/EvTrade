# rpc-protocol delta — 字段名约定（broker 原字段名 vs server 内部命名）

## MODIFIED Requirements

### REQ-RPC-003 响应解析 — 字段名透传

**原文本**（`openspec/specs/rpc-protocol/spec.md:35-40`）：

> ### REQ-RPC-003: 响应解析
> - RPC 响应统一 2 个结果集：
>   - **RS1**: `{code: int, msg: str}` — 状态码 + 错误信息
>   - **RS2**: `list[dict]` — 业务数据
> - `code=0` 表示成功
> - 业务函数 `_parse_*` 把 RS2 转成 TypedDict / Pydantic model

**新文本**：

> ### REQ-RPC-003: 响应解析（v10 字段名约定）
> - RPC 响应统一 2 个结果集：
>   - **RS1**: `{code: int, msg: str}` — 状态码 + 错误信息
>   - **RS2**: `list[dict]` — 业务数据（**字段名严格遵循 `iquant/xtquant_api.py` 柜台协议**）
> - `code=0` 表示成功
> - 业务函数 `_parse_*` 把 RS2 转为内部 dict 时**保留 broker 原始字段名**（snake_case，`traded_id`/`avl_amt`/`avg_price` 等）
> - 内部命名映射（如 `traded_id` → `trade_id`、`avl_amt` → `avl_vol`）由 **API 端点**通过 Pydantic / ORM 完成，**不在 parsers 层做重命名**

### REQ-RPC-004 业务函数列表 — 字段映射表

**新增表格**（追加到 REQ-RPC-004 后）：

> ### REQ-RPC-004.1: 业务字段映射表（v10 broker 原字段名）
>
> | RPC func | broker 字段（xtquant 协议） | server 内部命名（DB/API） |
> |---|---|---|
> | `qry_pos` | `stock_code, last_vol, volume, avl_amt, avg_price, market_value` | `stock_code, last_vol, vol, avl_vol, cost_price, market_value`（API 层映射） |
> | `qry_ord` | `order_id, stock_code, order_type, price_type, price, order_volume, traded_volume, traded_price, order_status, status_msg, strategy_name, order_remark, order_time` | `order_id, stock_code, order_type, price_type, price, volume, traded_volume, traded_price, status, status_msg, strategy_name, order_remark, order_time` |
> | `qry_ast` | `account_id, cash, frozen_cash, market_value, total_asset` | `cash, frozen_cash, market_value, total_asset`（`account_id` 透传不存储） |
> | `qry_mch` | `order_id, traded_id, stock_code, order_type, traded_volume, traded_price, traded_amount, strategy_name, order_remark, traded_time` | `order_id, trade_id, stock_code, order_type, volume, price, amount, strategy_name, order_remark, trade_time`（API 层映射） |
> | `cancel_ord` / `ord_stk` | `seq, order_id, result` | 透传 |
>
> 字段名权威源：`iquant/xtquant_api.py` 第 130-200 行（query handler）和 280-340 行（push callback）。

### REQ-RPC-010: 时间戳字符串化（v10 新增）

**新增段落**：

> ### REQ-RPC-010: 时间戳统一格式（v10 新增）
> - 所有 API 响应 / WS broadcast 中的时间戳字段统一为字符串格式 `"YYYY-MM-DD HH:MM:SS.fff"`（23 字符，毫秒精度）
> - **业务时间戳**（order_time / trade_time / order 创建时间）使用**本地时间**（与 QMT 柜台一致）
> - **系统时间戳**（created_at / updated_at / pushed_at / synced_at）使用 **UTC**（DB 内部 `DateTime`，序列化时 `format_db_dt()` 转字符串）
> - DB 列 `Order.order_time` / `Trade.trade_time` 类型：`String(23)`（从 `String(8)` 升级，原 "HH:MM:SS" 改为完整日期时间）
> - 统一入口：`server/services/push_helpers.py:format_ts()` / `parse_broker_ts()` / `format_db_dt()`
> - 兼容：broker 推送的 `order_time` / `traded_time` 可能是 "HH:MM:SS" / "HHMMSS" / "YYYYMMDDHHMMSS" / "YYYYMMDDHHMMSSfff" 中任一格式，由 `parse_broker_ts()` 统一解析为标准格式

## 勘误历史

- 2026-06-25 修订：parsers 之前用内部字段名（`status`/`available`/`cost`/`trade_id`/`trade_time` 等）覆盖 broker 原字段名，导致 push handler / API / 对账路径出现 `row.get('available')` 之类的散落兼容代码；改为 broker 原字段名 + API 层显式映射（单一职责）
