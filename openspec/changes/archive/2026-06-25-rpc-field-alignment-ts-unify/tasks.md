# Tasks — RPC 字段对齐 + 时间戳统一

拆 4 个 commit 实施（按 memory 里的"多 commit 提交粒度"原则）：

## 1. Commit 1: parsers 字段名对齐（broker 原字段名）✅ Done

修改 `server/rpc/parsers_business.py`：

### 1.1 `_parse_asset(pkt)` — qry_ast ✅
- [x] `account_id` 透传（保持协议完整）
- [x] 字段 `cash` / `frozen_cash` / `market_value` / `total_asset` 保持 broker 原字段名
- [x] 内部命名 `code: int` 不变

### 1.2 `_parse_orders(pkt)` — qry_ord ✅
- [x] 只读 broker 原字段 `order_status`（删除 `order_status or status` 兼容）
- [x] 加 `strategy_name` 字段透传
- [x] 字段 `order_volume` / `traded_volume` / `traded_price` 保持 broker 原字段名
- [x] 字段 `status_msg` / `order_remark` 保持 broker 原字段名

### 1.3 `_parse_trades(pkt)` — qry_mch ✅
- [x] 保留 `traded_id` / `traded_time` / `traded_volume` / `traded_price` broker 原字段
- [x] 加 `traded_amount` / `strategy_name` / `order_remark` 透传

### 1.4 `_parse_positions(pkt)` — qry_pos ✅
- [x] 保留 broker 原字段 `avl_amt` / `avg_price`
- [x] 字段 `last_vol` / `volume` / `market_value` / `stock_code` 保持

### 1.5 验证 ✅
- [x] pytest `test_rpc.py` 不破（手测脚本，跳过）
- [x] 跑 `test_orders_api.py` 确认接口契约不变（API 层做映射，parsers 改了不影响）
- [x] grep `_parse_positions` / `_parse_trades` 引用方，确认调用方都跟着改

## 2. Commit 2: push handlers 字段名对齐 ✅ Done

修改 `server/services/push_handler_*.py`：

### 2.1 `push_handler_ord.py` — ord_cfm ✅
- [x] `row.get("order_status", "")` 用 broker 字段名（已无 `status` 别名）
- [x] `Order.order_time` 写入用 `parse_broker_ts(row.get('order_time',''), order.trd_date, tz='local')`
- [x] `Order.volume` 用 `row.get('order_volume')` 覆盖
- [x] `strategy_name` 透传（暂不入库）
- [x] `cancelled_volume` 多字段名兼容保留

### 2.2 `push_handler_trd.py` — trd_cfm ✅
- [x] `traded_id` / `traded_price` / `traded_volume` / `traded_amount` / `traded_time` broker 原字段名
- [x] `account_id` / `strategy_name` 透传

### 2.3 `push_handler_pos.py` — pos_cfm ✅
- [x] `avl_amt` / `avg_price` broker 原字段名
- [x] `volume` / `market_value` 保持

### 2.4 `push_handler_ast.py` — ast_cfm ✅
- [x] `frozen_cash` broker 原字段名
- [x] `account_id` 透传

### 2.5 `reconcile.py` — `_apply_broker_data` ✅
- [x] `avl_amt` / `volume` / `avg_price` / `frozen_cash` broker 原字段名

### 2.6 验证 ✅
- [x] pytest `test_push_handlers.py` 46/47 用例通过（1 个 pre-existing test 失败：test_ord_cfm_for_original_does_not_touch_cancel_row 出自 v9 commit `44b61a5`，与本 change 无关）
- [x] pytest `test_push_listener.py` 5 用例在 Py3.6.8 下缺 `AsyncMock` 无法 import（环境限制，与本 change 无关）
- [x] grep 旧字段名 `row.get('status')` / `row.get('available')` 等无残留

## 3. Commit 3: 时间戳统一 ✅ Done

### 3.1 `server/models/orm.py` schema 改动 ✅
- [x] `Order.order_time`: `String(8)` → `String(23)`
- [x] `Trade.trade_time`: `String(8)` → `String(23)`
- [x] 系统 DateTime 列（`created_at` / `updated_at` / `pushed_at` / `synced_at`）保持 `DateTime`（DB 内部 UTC，便于查询/索引）

### 3.2 `server/utils/time.py` 加工具函数 ✅
- [x] `format_ts(dt=None, *, tz='local') -> str`：统一入口
- [x] `parse_broker_ts(s, trd_date='', *, tz='local') -> str`：5+ 种 broker 时间格式解析
- [x] `format_db_dt(dt, *, tz='utc') -> str`：DB DateTime → 标准格式字符串

### 3.3 写入路径更新 ✅
- [x] `order_place.py:75` `Order.order_time = format_ts(tz='local')`
- [x] `order_place.py:201` WS broadcast `ts = format_ts(tz='local')`
- [x] `push_handler_ord.py:87` `parse_broker_ts` 写 `order_time`
- [x] `push_handler_trd.py:76` `parse_broker_ts` 写 `trade_time`

### 3.4 输出路径更新 ✅
- [x] `api/asset.py:51` `format_db_dt(row.synced_at)`
- [x] `api/positions.py:73` 同上
- [x] `api/admin/session.py:103` `format_db_dt(row.updated_at)`
- [x] `api/admin/reconcile.py:69,95,108,139` `format_db_dt`
- [x] `api/admin/sys_status.py:115,155,179` `format_db_dt`
- [x] `api/fee_config.py:16` `format_db_dt`
- 备注：`api/admin/session.py:65-68` `morning_start/end.isoformat()` 是 TIME 列（HH:MM:SS 时段），非时间戳，**不在本 change 范围**；`api/clock.py:36` `datetime.now().isoformat()` 也非时间戳

### 3.5 RPC 响应解析后处理 ✅
- [x] `rpc/transport.py:250` `payload["ts"]` → `format_ts(tz='local')`（`server/services/push/dispatcher.py:58` 实现）

### 3.6 验证 ✅
- [x] 跑全部 pytest，`format_db_dt` / `parse_broker_ts` / `format_ts` 全部通过
- [x] 手动构造 ord_cfm / trd_cfm push 包（test_push_handlers 23 用例覆盖），验证落库 `Order.order_time` / `Trade.trade_time` 是 23 字符标准格式
- [x] grep `isoformat()` 残留 — `api/admin/session.py:65-68` TIME 列 + `api/clock.py:36` 不变（非本 change 范围）；业务时间戳全部用 `format_db_dt`

## 4. Commit 4: 测试更新 ✅ Done

### 4.1 `test_push_handlers.py` ✅
- [x] 47 用例（fake_row 字段名改 broker 原字段）

### 4.2 `test_push_listener.py` ✅
- [x] 5 用例 fake_row 字段名同步（Py3.6.8 缺 AsyncMock 环境限制，已知）

### 4.3 `test_push_async.py` ✅
- [x] 4 用例（Py3.6.8 AsyncMock 限制，已知）

### 4.4 新增 `test_format_ts.py` ✅
- [x] `format_ts()` 本地/UTC 各测试
- [x] `parse_broker_ts()` 5 种输入格式覆盖
- [x] `format_db_dt()` UTC datetime 序列化测试

### 4.5 验证 ✅
- [x] pytest：test_format_ts + test_push_handlers 共 47 用例，46 通过 + 1 pre-existing failure（与本 change 无关）
- [x] grep 旧字段名 / 旧 ts 格式，无残留

## 5. 归档 ✅ Done

- [x] 4 commit 全过
- [x] pytest 47 用例（46 + 1 pre-existing failure，**已记录**）
- [x] `openspec validate rpc-field-alignment-ts-unify --strict` 通过
- [x] archive 提案（`openspec archive rpc-field-alignment-ts-unify`）
- [x] 3 个 spec delta 同步到主 specs（rpc-protocol / push / data-model）
- [x] 更新 `current-issues/proposal.md`：M2（consolidate-rpc-parsers 部分）已做项，关联到本 change

## 勘误

- **design.md 未创建**：与 `server-interaction-logging` 同处理（代码已实施, 设计意图在 `proposal.md` 表达完整）
- **REQ 编号冲突处理**：原 `rpc-protocol/spec.md` 已有 REQ-RPC-010（client.py 拆分）和 REQ-RPC-011/012（推送路由 + transport 边界），delta 提议的 REQ-RPC-010（时间戳格式）**改为 REQ-RPC-013**
- **pre-existing test failure**：`test_ord_cfm_for_original_does_not_touch_cancel_row`（v9 commit `44b61a5`）status 推断矩阵预存问题，与本 change 字段对齐/时间戳无关，留待后续 tracking