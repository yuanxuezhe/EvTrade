# Tasks — RPC 字段对齐 + 时间戳统一

拆 4 个 commit 实施（按 memory 里的"多 commit 提交粒度"原则）：

## 1. Commit 1: parsers 字段名对齐（broker 原字段名）

修改 `server/rpc/parsers_business.py`：

### 1.1 `_parse_asset(pkt)` — qry_ast
- **删** `account_id` 字段在 server 端**不写入**（broker 推但 server 不需要）→ **加** `account_id` 字段透传（保持协议完整）
- 字段 `cash` / `frozen_cash` / `market_value` / `total_asset` 保持 broker 原字段名 ✓
- 内部命名 `code: int` 不变（broker 返回 "00000" 字符串，int 转换后供业务判断）

### 1.2 `_parse_orders(pkt)` — qry_ord
- 删除 `status = row.get("order_status") or row.get("status")` 这种兼容双字段的逻辑
- 改为只读 broker 原字段 `order_status`
- 加 `strategy_name` 字段透传
- 字段 `order_volume` / `traded_volume` / `traded_price` 保持 broker 原字段名 ✓
- 字段 `status_msg` / `order_remark` 保持 broker 原字段名 ✓

### 1.3 `_parse_trades(pkt)` — qry_mch
- 删除 `traded_id` → `trade_id` 重命名，**保留** `trade_id` 作为 broker 原字段
- 删除 `traded_time` → `trade_time` 重命名，**保留** `trade_time` 作为 broker 原字段
- 删除 `traded_volume` → `volume` 重命名，**保留** `traded_volume` 作为 broker 原字段
- 删除 `traded_price` → `price` 重命名，**保留** `traded_price` 作为 broker 原字段
- **加** `traded_amount` / `strategy_name` / `order_remark` 透传

### 1.4 `_parse_positions(pkt)` — qry_pos
- 删除 `avl_amt` → `available` 重命名，**保留** broker 原字段 `avl_amt`
- 删除 `avg_price` → `cost` 重命名，**保留** broker 原字段 `avg_price`
- 字段 `last_vol` / `volume` / `market_value` / `stock_code` 保持 ✓

### 1.5 验证
- [ ] pytest `test_rpc.py` 不破（手测脚本，跳过）
- [ ] 跑 `test_orders_api.py` 确认接口契约不变（API 层做映射，parsers 改了不影响）
- [ ] grep `_parse_positions` / `_parse_trades` 引用方，确认调用方都跟着改

## 2. Commit 2: push handlers 字段名对齐

修改 `server/services/push_handler_*.py`：

### 2.1 `push_handler_ord.py` — ord_cfm
- `row.get("status", "")` → `row.get("order_status", "")`（broker 字段名）
- 加 `row.get("order_time", "")` 解析后写入 `Order.order_time`（标准格式）
- 加 `row.get("order_volume", "")` 解析后写入 `Order.volume`（覆盖用户后续改单后的真实 volume）
- 加 `row.get("strategy_name", "")` 写入（暂时不入库，仅日志保留 / 透传给 WS）
- `cancelled_volume` 字段名兼容保留（v8 决策，broker 实际可能 `cancelled_volume` / `cancel_volume` / `withdrawn_volume`，保留多字段兜底）

### 2.2 `push_handler_trd.py` — trd_cfm
- `row.get("trade_id", "")` → `row.get("traded_id", "")`（broker 字段名）
- `row.get("price", "")` → `row.get("traded_price", "")`（broker 字段名）
- `row.get("volume", "")` → `row.get("traded_volume", "")`（broker 字段名）
- `row.get("amount", "")` → `row.get("traded_amount", "")`（broker 字段名）
- `row.get("trade_time", "")` → `row.get("traded_time", "")`（broker 字段名）
- 加 `row.get("account_id", "")` / `row.get("strategy_name", "")` 字段透传（暂时不入库）

### 2.3 `push_handler_pos.py` — pos_cfm
- `row.get("available", 0)` → `row.get("avl_amt", 0)`（broker 字段名）
- `row.get("cost_price", ...)` → `row.get("avg_price", ...)`（broker 字段名）
- `row.get("volume", 0)` 保持 ✓
- `row.get("market_value", 0)` 保持 ✓（与 broker 一致）

### 2.4 `push_handler_ast.py` — ast_cfm
- `row.get("frozen", 0)` → `row.get("frozen_cash", 0)`（broker 字段名）
- 加 `row.get("account_id", "")` 透传
- 其它字段名已对齐 ✓

### 2.5 `reconcile.py` — `_apply_broker_data`
- 持仓 `avl_vol = p.get('avl_vol', p.get('available', 0))` → 改为 `avl_vol = p.get('avl_amt', 0)`
- 持仓 `vol = p.get('vol', p.get('volume', 0))` → 改为只 `vol = p.get('volume', 0)`（broker 实际只送 `volume`）
- 持仓 `cost_price = p.get('cost_price', p.get('cost', 0))` → 改为 `cost_price = p.get('avg_price', 0)`
- 资金 `frozen_cash = a.get('frozen_cash', a.get('frozen', 0))` → 改为 `frozen_cash = a.get('frozen_cash', 0)`
- 其它 `cash` / `market_value` / `total_asset` 保持 ✓

### 2.6 验证
- [ ] pytest `test_push_handlers.py` 23 用例全过（更新 fake_row 字段名）
- [ ] pytest `test_push_listener.py` 5 用例全过（fake_row 同步）
- [ ] grep 旧字段名 `row.get('status')` / `row.get('available')` 等无残留

## 3. Commit 3: 时间戳统一

### 3.1 `server/models/orm.py` schema 改动
- `Order.order_time`: `String(8)` → `String(23)`，注释更新为 `"YYYY-MM-DD HH:MM:SS.fff"`
- `Trade.trade_time`: `String(8)` → `String(23)`
- 系统 DateTime 列（`created_at` / `updated_at` / `pushed_at` / `synced_at`）保持 `DateTime`（DB 内部 UTC，便于查询/索引），序列化由 API 层做

### 3.2 `server/services/push_helpers.py` 加工具函数
- 新增 `format_ts(dt=None, *, tz='local') -> str`：统一入口
  - `dt is None` → 用 `datetime.now()`
  - `tz='local'` → 本地时区，输出 `"2026-06-24 17:56:28.281"`
  - `tz='utc'` → UTC，输出同上（无 Z 后缀）
- 新增 `parse_broker_ts(s: str, trd_date: str = '', tz='local') -> str`：
  - 输入 `"HH:MM:SS"` / `"HHMMSS"` / `"YYYYMMDDHHMMSS"` / `"YYYYMMDDHHMMSSfff"` / `"2026-06-24 17:56:28.281"`
  - 输出标准格式
  - `trd_date` 用于"HH:MM:SS"补全日期部分
- 新增 `format_db_dt(dt: datetime, *, tz='local') -> str`：把 `DateTime`（naive UTC）序列化为标准格式字符串

### 3.3 写入路径更新
- `order_place.py:89` `Order` 创建 → `order_time=format_ts(tz='local')`
- `order_place.py:201` WS broadcast `ts` → `format_ts(tz='local')`
- `order_place.py:198-218` WS payload data 字段同步
- `push_handler_ord.py` `order_time` 写入 → `parse_broker_ts(row.get('order_time',''), order.trd_date, tz='local')`
- `push_handler_trd.py` `trade_time` 写入 → `parse_broker_ts(row.get('traded_time',''), trd_date, tz='local')`

### 3.4 输出路径更新
- `api/asset.py:47` `synced_at=row.synced_at.isoformat() if ...` → `synced_at=format_db_dt(row.synced_at) if ...`
- `api/positions.py:73` 同上
- `api/order_query.py:46` 排序 `desc(Order.order_time)` 保持（列还是 String，23 字符字典序 = 时间序）
- `api/admin/session.py:69` `updated_at=...` → `format_db_dt`
- `api/admin/reconcile.py:37,68` 同上
- `api/admin/sys_status.py` 如有 datetime 输出 → `format_db_dt`
- `models/user.py:39-40` `created_at` / `updated_at` → `format_db_dt`

### 3.5 RPC 响应解析后处理（push 数据广播）
- `rpc/transport.py:250` `payload["ts"]` → `format_ts(tz='local')`（覆盖 broker 推的紧凑 ts，统一格式）
- `rpc/transport.py:240-252` `enriched_row` 不变（broker 字段名透传）

### 3.6 验证
- [ ] 跑全部 pytest，**预期**老断言 `assert order_time == "09:30:00"` 类需要更新
- [ ] 手动构造 ord_cfm / trd_cfm push 包，验证落库后 `Order.order_time` / `Trade.trade_time` 是 23 字符标准格式
- [ ] grep `isoformat()` 残留（除 `user.py` ORM helper 内部），全替换为 `format_db_dt`

## 4. Commit 4: 测试更新

### 4.1 `test_push_handlers.py`
- 23 个用例 fake_row 字段名改 broker 原字段（见 commit 2 字段表）
- 16 处 `ts="20260614 09:30:00"` / `ts="x"` → 改标准格式

### 4.2 `test_push_listener.py`
- 5 个用例 fake_row 字段名同步（`status` → `order_status`、`volume` 保留、`price` → `traded_price` 等）

### 4.3 `test_push_async.py`
- 4 个用例不直接涉及字段名/时间字符串，但需检查断言

### 4.4 新增 `test_format_ts.py`
- `format_ts()` 本地/UTC 各测试
- `parse_broker_ts()` 5 种输入格式覆盖
- `format_db_dt()` UTC datetime 序列化测试

### 4.5 验证
- [ ] pytest 全绿（19+23+5+4+1+其它 = 至少 52 用例）
- [ ] grep 旧字段名 / 旧 ts 格式，无残留

## 5. 归档

- [ ] 4 commit 全过
- [ ] pytest 100% 绿
- [ ] `openspec validate rpc-field-alignment-ts-unify --strict` 通过
- [ ] archive 提案（`openspec archive rpc-field-alignment-ts-unify`）
- [ ] 更新 `current-issues/proposal.md`：移除 M2（consolidate-rpc-parsers 部分）已做项，关联到本 change
