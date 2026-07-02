# rpc-protocol — msgpacket RPC 客户端契约

## Purpose

后端通过 msgpacket 协议（YSWY）经 RabbitMQ 调用 QMT 柜台。
RPC 客户端统一封装：构造包、发送、等待 reply、超时、解析。
**所有业务代码**（api/）只能调用 `qry_*` / `ord_stk` / `cancel_order`，**不直接**碰 `RPClient.call()`。

## Requirements

### REQ-RPC-001: 客户端生命周期

- `get_rpc_client()` — 单例，启动时自动 connect + 启动 reply/push listener
- `close_rpc_client()` — 关闭连接（在 FastAPI shutdown 钩子中调用）
- 重复调用 `get_rpc_client()` 返回同一实例

### REQ-RPC-002: 调用语法

```python
pkt = await client.call(
    func,                      # 柜台函数名
    headers="field1,field2",   # 字段名（逗号分隔，对应 YSWY 包头）
    values={"field1": "...", "field2": "..."},  # 字段值
    timeout=30.0,              # 可选，默认 30s
)
```

`headers` 和 `values` 是必填（即便空也要传 `headers=""` 占位）。

### REQ-RPC-003: 响应解析

- RPC 响应统一 2 个结果集：
  - **RS1**: `{code: int, msg: str}` — 状态码 + 错误信息
  - **RS2**: `list[dict]` — 业务数据（broker 原字段名透传，v10 起）
- `code=0` 表示成功；非 0 时 `list` 可为空
- 业务函数 `_parse_*`（位于 `server/rpc/parsers_business.py`）把 RS2 转成 `Dict[str, Any]`，
  统一返回 `{code, msg, list}` 形状（consolidate-rpc-parsers 改动）
- 字段映射容错：缺失字段用 `_to_int` / `_to_float` 默认 0；类型不匹配降级为默认值（不抛 ValidationError）
- **未实施**：Pydantic `BaseModel` 化（提案建议但未执行；当前 `Dict[str, Any]` 已足，typed via docstring 字段列表）

### REQ-RPC-004: 业务函数列表

| 函数 | RPC func | 解析器 | 返回 |
|---|---|---|---|
| `qry_asset` | `qry_asset` | `_parse_asset` | `{code, msg, list: [Asset]}` |
| `qry_orders` | `qry_orders` | `_parse_orders` | `{code, msg, list: [Order]}` |
| `qry_trades` | `qry_mch` | `_parse_trades` | `{code, msg, list: [Trade]}` |
| `qry_positions` | `qry_pos` | `_parse_positions` | `{code, msg, list: [Position]}` |
| `ord_stk` | `ord_stk` | `_parse_order_ack` | `{code, msg, list: [OrderAck]}` |
| `cancel_order` | `cancel_ord` | `_parse_order_ack` | `{code, msg, list: [OrderAck]}` |

### REQ-RPC-004.1: 业务字段映射表（v10 broker 原字段名，rpc-field-alignment-ts-unify 实施）

| RPC func | broker 字段（xtquant 协议） | server 内部命名（DB/API） |
|---|---|---|
| `qry_pos` | `stock_code, last_vol, volume, avl_amt, avg_price, market_value` | `stock_code, last_vol, vol, avl_vol, cost_price, market_value`（API 层映射） |
| `qry_ord` | `order_id, stock_code, order_type, price_type, price, order_volume, traded_volume, traded_price, order_status, status_msg, strategy_name, order_remark, order_time` | `order_id, stock_code, order_type, price_type, price, volume, traded_volume, traded_price, status, status_msg, strategy_name, order_remark, order_time` |
| `qry_ast` | `account_id, cash, frozen_cash, market_value, total_asset` | `cash, frozen_cash, market_value, total_asset`（`account_id` 透传不存储） |
| `qry_mch` | `order_id, traded_id, stock_code, order_type, traded_volume, traded_price, traded_amount, strategy_name, order_remark, traded_time` | `order_id, trade_id, stock_code, order_type, volume, price, amount, strategy_name, order_remark, trade_time`（API 层映射） |
| `cancel_ord` / `ord_stk` | `seq, order_id, result` | 透传 |

字段名权威源：`iquant/xtquant_api.py` 第 130-200 行（query handler）和 280-340 行（push callback）。

**单一职责**：
- parsers 层：broker 原字段名透传，不做内部命名映射
- API 层：通过 Pydantic / ORM 完成 `traded_id` → `trade_id`、`avl_amt` → `avl_vol`、`avg_price` → `cost_price` 等映射
- 之前的 parsers 内部重命名（`traded_id` → `trade_id`、`avl_amt` → `available` 等）已废弃，导致 push handler / API / 对账路径出现 `row.get('available')` 之类的散落兼容代码

#### REQ-RPC-004.1: broker status 字段重映射（v11 新增段）

`qry_ord` 响应 `order_status` 字段值 MUST 直接写入 `Order.status`，无翻译层（v10 之前是"本地推断码语义", 现在是 broker 字典直接对齐）。`push_handler_ord` 收到 broker 推 `order_status` 字段 MUST 直接采用, 不调用任何翻译函数。字段名唯一权威: broker 原字段名 (`order_status`), 不再 alias `status`。

#### Scenario: qry_ord 响应 status 直接采用 broker 码（v11 新增）

- **WHEN** `qry_ord` 响应 RS2 含 `order_status='54'`（broker CANCELED）
- **THEN** API 层 Pydantic 序列化时映射为 `status='54'`
- **AND** 前端 view 按 broker 字典解读: `STATUS_LABEL['54']` = '已撤'
- **AND** 跨系统对账时无需翻译

#### Scenario: push handler 直接采用 broker order_status（v11 新增）

- **WHEN** broker 推 `ord_cfm` row 含 `order_status='57'`（broker JUNK 废单）
- **THEN** `push_handler_ord` 直接写 `Order.status='57'`, 不调用 `_status_msg` 翻译
- **AND** 前端 view 按 broker 字典解读: `STATUS_LABEL['57']` = '废单'

#### Scenario: 跨系统对账无需翻译（v11 新增）

- **WHEN** 对账脚本读取 broker `qry_ord` 响应 vs 本地 DB `orders.status`
- **THEN** broker `order_status='54'` 与本地 `status='54'` 是同一字典同一码, 无需翻译表

#### Scenario: qry_ord 字段映射（v11 修订）

- **WHEN** `qry_ord` 响应 RS2 包含 `order_status` 字段
- **THEN** 业务字段映射表 MUST 标记 `order_status` → `status` 直接采用 broker 码, 无翻译
- **AND** 之前的"本地推断码语义"层（`Status._LABEL` / `ORDER_STATUS` legacy / 前端 `STATUS_LABEL` 错位）全部废弃

### REQ-RPC-005: 超时与重试

- 默认超时 30s
- 超时后 reply 关联的 future 清理
- ❌ **不实现**重试（QMT 下单重试可能导致重复报单，副作用大）

### REQ-RPC-006: 错误处理

- 连接失败 → log + 返回 `{code: -1, msg: "RPC not connected", list: []}`
- 超时 → 同上 + log warning
- 解析失败 → log + 返回 `{code: -1, msg: "<error>", list: []}`

### REQ-RPC-007: 队列拓扑与绑定（v2 收紧）

- `connect()` 时**显式声明并绑定**三条 durable 队列到 `EXCHANGE_NAME`（topic）：
  - `EvTrade.Test.Req`    ← 发送 routing_key `EvTrade.Test.Req`
  - `EvTrade.Test.Reply`  ← 接收 routing_key `EvTrade.Test.Reply`
  - `EvTrade.Test.Push`   ← 接收 routing_key `EvTrade.Test.Push`
- 队列名直接作 routing_key（topic 通配 `*` / `#` 不依赖柜台侧预绑定）
- 重复 `connect()` 不报错（幂等）：已 connected 则直接返回
- 队列绑定失败（exchange 不存在 / 权限不足）→ 启动抛异常，不静默降级

### REQ-RPC-008: Publisher Confirms（v2 新增）

- channel 开启 `publisher_confirms=True`
- `exchange.publish()` 后**等 broker ack** 才返回（防 broker 重启/磁盘满导致静默丢包）
- 超时 5s 未 ack → 抛 `RuntimeError("publish unconfirmed")`，不挂起调用方
- RPClient 内部用 `_publish_confirm_timeout` 控制（默认 5s）

### REQ-RPC-009: 订单序号生成器原子性

`server/services/order_no.py:next_order_no(db)` 必须保证:

- **REQ-RPC-009.1** 原子自增, 实现允许两条路径:
  - (a) 理想方案: SQLite ≥ 3.35 单语句 `INSERT ... ON CONFLICT DO UPDATE ... RETURNING` 模式 (1 步)
  - (b) 兼容方案: SQLite ≥ 3.21 三步分离 `INSERT OR IGNORE` + `UPDATE` + `SELECT` 模式 (3 步, 函数内 commit)
  - 当前生产环境 Python 3.6.8 自带 SQLite 3.21.0, **必须使用方案 (b)**; 升级 Python 或 libsqlite3 后可切到 (a)
- **REQ-RPC-009.2** 函数内自动 commit (破坏旧"调用方负责 commit"约定), 消除"调用方异常回滚导致序号回退"风险
- **REQ-RPC-009.3** 返回 8 位数字字符串 '10000001'-'99999999', 达到上限时 raise RuntimeError
- **REQ-RPC-009.4** docstring 必须真实描述实现 (不得注释与代码不符)
- **REQ-RPC-009.5** 跨进程/线程安全 (依赖 SQLite 串行写入)

**旧约定废弃**:
- ❌ 调用方负责 commit → ✅ 函数内自动 commit
- ❌ 3 步分离语句 (INSERT OR IGNORE + UPDATE + SELECT) → ✅ 单语句 UPSERT

**调用方适配**:
- `server/api/orders.py:place_order` 调用 `next_order_no` 后 **不应** 立即 commit (函数内已 commit)
- `order_no` 跳号是 acceptable (下单失败 / 序号已 +1 但 Order 未入库, 与生产实际一致)

### REQ-RPC-010: client.py 拆分（phase-2）+ transport 缩为传输骨架（simplify-rpc-transport-thin）

client.py 677→76 行 facade 兼容垫片 + 6 个单一职责子模块；transport 模块在 phase-2 后又经过一次精简（simplify-rpc-transport-thin），最终仅承担 RPClient 传输骨架：

- `server/rpc/transport.py` (~380) — RPClient 传输骨架（connect / call / reply listener / push listener 骨架）+ 全局单例 + 2 个 wire utility（`_clean_id` / `_wire_dump`）
- `server/rpc/parsers_common.py` (~109) — 通用响应解析（`_select_rs` / `_parse_code_msg` / `_iter_rows` / `_to_*` / `_empty`）
- `server/rpc/parsers_business.py` (~152) — 业务特定解析（`_parse_asset` / `_parse_orders` / `_parse_trades` / `_parse_positions` / `_parse_order_ack`）
- `server/rpc/parsers_push.py` (~30) — push 行提取（`_iter_push_rows`），与 parsers_common._iter_rows 思路不同（不做类型转换）
- `server/rpc/handlers.py` (~100) — 业务 RPC 入口（`qry_asset` / `qry_orders` / `qry_trades` / `qry_positions` / `ord_stk` / `cancel_order`）
- `server/services/push_dispatcher.py` (~200) — push 业务编排（`_run_handle_push` / `_resolve_active_trd_date_safe` / `_log_push_interaction` / `_log_push_broadcast` / `_dispatch_push` / `_broadcast_trade_cfm` / `_broadcast_generic`）+ `_PUSH_CHANNEL` 路由表；`PushDispatcher` 类

**契约**：
- 既有 `from rpc.client import ...` 仍可解析（13 import 站点全过）
  - `test_rpc.py` / `test_rpc_link.py` 用 `from rpc.client`（cwd=server）
  - `api/orders.py` / `main.py` / `services/reconcile.py` 用 `from server.rpc.client`
  - 全部符号在 facade re-export，来源分别从 transport / parsers_*.py / services.push_dispatcher 取
- 子模块间单向依赖：
  - transport → parsers_push（仅模块顶层 type hint）/ services.push_dispatcher（callback）/ services.push_handlers / services.guards / ws_manager
  - services.push_dispatcher → services.push_handlers / services.guards / ws_manager / utils.logflow / utils.time
  - handlers → parsers_business → parsers_common
  - 无环
- `parsers_push._iter_push_rows` 是 push 链路专用的行提取器（与 parsers_common._iter_rows 思路不同：不做类型转换），归属 rpc/parsers_push.py
- `RPClient` 在 `connect()` 时构造 `self._dispatcher = PushDispatcher(self)`；push listener 仅调 `dispatcher.dispatch(pkt, func, msg_type, wire_len)`，不持有任何 push 业务逻辑

#### Scenario: facade re-export 不破坏既有 import
- **WHEN** 业务代码 `from server.rpc.client import _run_handle_push` 仍能解析
- **THEN** 该符号现指向 `services.push_dispatcher._run_handle_push`，但调用签名 `(func: str, row: Dict[str, Any], ts: str) -> Optional[Dict[str, Any]]` 不变
- **AND** `test_push_handlers.py` 11 用例零改动继续通过

#### Scenario: transport 不再依赖 services
- **WHEN** 静态检查 `server/rpc/transport.py` 的 import
- **THEN** 不出现 `from server.services.push_handlers / push_dispatcher 之外的间接依赖通过 dispatcher 隔离）` / `from server.ws.*` / `from server.db import SessionLocal`（release 后唯一保留的 transport 内部 import 是 aio_pika / msgpacket / server.config）

### REQ-RPC-011: 推送类型 → WS channel 映射表（v1，simplify-rpc-transport-thin 后归属 dispatcher）

- 位置：`server/services/push_dispatcher.py::_PUSH_CHANNEL`
- 映射：
  - `ord_cfm` → `order_update`
  - `trd_cfm` → `trade_update`
  - `pos_cfm` → `position_update`
  - `ast_cfm` → `asset_update`
- 用途：`PushDispatcher.dispatch` 收到 push 后查表决定 WS 频道
- 未知 func：log warning + skip（不广播）
- **历史位置**：`server/rpc/transport.py::_PUSH_CHANNEL`（v1 引入），simplify-rpc-transport-thin 后迁出到 services/push_dispatcher.py

#### Scenario: 未知 func 不广播
- **WHEN** dispatcher.dispatch(pkt, func="unknown_cfm", ...)
- **THEN** 打 warning 日志
- **AND** 不调用 ws_manager.broadcast

### REQ-RPC-012: transport 模块边界约束（simplify-rpc-transport-thin）

`server/rpc/transport.py` SHALL NOT 依赖以下模块（避免 push 业务逻辑再次渗透）：

- `server.services.*`（除 `services.push_dispatcher` 之外；`PushDispatcher` 类是该模块对外的唯一耦合点）
- `server.ws.*`（ws_manager 访问由 dispatcher 持有）
- `server.db.*`（SessionLocal 创建由 dispatcher 持有）
- `server.utils.time` / `server.utils.logflow` 的 push 相关符号（push 交互日志由 dispatcher 持有）

`transport.py` 允许的 import 范围：

- `aio_pika` / `msgpacket` — 传输协议
- `asyncio` — event loop
- `logging` — transport 自身日志（如 publisher confirm timeout）
- `server.config.settings` — 配置（RABBITMQ_URL / EXCHANGE_NAME / 队列名 / RPC_TIMEOUT）
- `server.services.push_dispatcher.PushDispatcher` — push 业务编排入口

push listener 在收到消息后 SHALL 立即调 `dispatcher.dispatch(pkt, func, msg_type, wire_len)`，不解析数据、不查询 DB、不构造 WS payload、不写 push 交互日志。

> 注：RPC `call()` 方法内部 lazy import `server.utils.logflow` / `server.rpc.parsers_common` 用于 RPC 调用侧的可追溯日志（REQ-LOG-003 svc→rpc / svc←rpc），属于传输层可追溯性而非 push 业务编排，本约束不覆盖。

#### Scenario: transport.py 静态边界扫描通过
- **WHEN** 用 grep 扫 `server/rpc/transport.py` 的 `from server.` import 语句
- **THEN** 顶层仅命中 `server.config` 和 `server.services.push_dispatcher`，不命中 `server.services.push_handlers` / `server.services.guards` / `server.ws.*` / `server.db.*` / `server.utils.*`

#### Scenario: push listener 不解析 push 数据
- **WHEN** push listener 收到一条 `ord_cfm` 消息
- **THEN** transport 只做三件事：解码 MsgPacket、提取 func / msg_type、调 `self._dispatcher.dispatch(...)`
- **AND** 不出现 `_iter_push_rows` / `_run_handle_push` / `_PUSH_CHANNEL` / `_log_push_*` 等 push 业务符号

### REQ-RPC-013: 时间戳统一格式（v10 新增，rpc-field-alignment-ts-unify 实施）

所有 API 响应 / WS broadcast 中的时间戳字段 MUST 统一为字符串格式 `"YYYY-MM-DD HH:MM:SS.fff"`（23 字符，毫秒精度）：

- **业务时间戳**（`order_time` / `trade_time` / Order 创建时间）MUST 使用**本地时间**（与 QMT 柜台一致）
- **系统时间戳**（`created_at` / `updated_at` / `pushed_at` / `synced_at`）MUST 使用 **UTC**（DB 内部 `DateTime`，序列化时 `format_db_dt()` 转字符串）
- DB 列 `Order.order_time` / `Trade.trade_time` 类型 MUST 为 `String(23)`（从 `String(8)` 升级，原 `"HH:MM:SS"` 改为完整日期时间）
- 统一入口 MUST 是 `server/utils/time.py`：`format_ts()` / `parse_broker_ts()` / `format_db_dt()`
- **兼容**：broker 推送的 `order_time` / `traded_time` 可能是 `"HH:MM:SS"` / `"HHMMSS"` / `"YYYYMMDDHHMMSS"` / `"YYYYMMDDHHMMSSfff"` 中任一格式，MUST 由 `parse_broker_ts()` 统一解析为标准格式
- 禁止使用 `isoformat()` / `time.time()` / 紧凑 14 位串 等其他格式（业务时间戳列）

#### Scenario: 业务时间戳格式校验

- **WHEN** 任何 API 响应（如 `/api/orders` / `/api/trades`）序列化 Order.order_time 或 Trade.trade_time
- **THEN** 字符串 MUST 匹配正则 `^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}$`，长度为 23 字符

#### Scenario: 系统时间戳序列化

- **WHEN** API 响应序列化 `created_at` / `updated_at` / `synced_at` 等 DateTime 列
- **THEN** MUST 调 `format_db_dt(dt, tz='utc')` 输出标准格式字符串

#### Scenario: broker 时间格式兼容

- **WHEN** push handler 收到 broker 推的 `order_time="09:30:00"`（仅 HH:MM:SS）
- **THEN** `parse_broker_ts("09:30:00", order.trd_date, tz='local')` MUST 输出 `"2026-06-14 09:30:00.000"`（trd_date 补全日期部分）

#### Scenario: 禁止 isoformat 替代

- **WHEN** developer 写 `order.created_at.isoformat()` 序列化 DateTime 列
- **THEN** code review MUST 拒收；正确写法为 `format_db_dt(order.created_at)`

## Scenarios

### S-RPC-001: 正常查询

Given RPC 已连接，柜台在线  
When `qry_orders()`  
Then 30s 内返回 `{code: 0, msg: "", list: [Order...]}`

### S-RPC-002: 柜台断连

Given aio_pika.connect_robust 心跳超时  
When `qry_orders()`  
Then `connect_robust` 自动重连  
And 期间调用的 `_parse_*` 返回 `{code: -1, ...}`

### S-RPC-003: 错误传参

When `ord_stk(order_type="invalid")`  
Then 柜台返回 `{code: -100, msg: "order_type 非法", list: []}`  
And 后端原样透传

### S-RPC-004: 队列绑定（v2）

Given 服务启动 `connect()`  
When 检查 broker 队列表  
Then `EvTrade.Test.Req` / `EvTrade.Test.Reply` / `EvTrade.Test.Push` 均存在  
And 三条队列的 binding source exchange = `EXCHANGE_NAME`，routing_key = 各自队列名

### S-RPC-005: Publisher Confirm 超时（v2）

Given broker 停止 ack（mock 故障）  
When `call("qry_ast")`  
Then 5s 内抛 `RuntimeError("publish unconfirmed")`  
And `pending` dict 不残留（避免后续应答误匹配）

## Code Reference

- `server/rpc/client.py` — 客户端主体
- `server/rpc/client.py:23-24` — func → WS 频道映射（ord_cfm/trd_cfm）
- `server/rpc/client.py:530-571` — 业务函数实现
- `server/rpc/client.py:478+` — `_parse_ord_cfm`（push 专用，与查询解析器不同）

### REQ-RPC-013: API 响应格式统一（v10 M6 折叠）

所有 `/api/*` 查询端点统一返回 `{"code": int, "msg": str, "list": [...]}` 形状：

- `asset.py` 端点从 `{code, msg, data: AssetOut}` 改为 `{code, msg, list: [AssetOut]}`（包单元素数组）
- `orders / trades / positions / holdings` 端点维持 `{code, msg, list: [...]}`
- 前端 axios 拦截器统一解包 `list` 字段（删除 `_parseAsset(resp.data.data)` 特殊处理）
- `code != 0` 时 `list` 可为空数组

#### Scenario S-RPC-006: asset 端点响应格式

Given 用户调 `GET /api/asset`
When 收到响应
Then `resp.data` = `{code: 0, msg: "", list: [{account_id: ..., cash: ..., ...}]}`（**list 而非 data**）
And `list[0]` 是单元素（asset 是单账户查询）

## Known Issues (from analysis)

- ✅ 8 个 `_parse_*` 解析器统一 shape：所有解析器返 `{code, msg, list}`（`server/rpc/parsers_business.py`）
- ✅ `cancel_order` 占位实现已修（v9 重构后走真实 RPC + late import）
- ✅ `ord_cfm` push 解析器与查询解析器不复用是合理的（字段确实不同）
- 🟡 Pydantic `BaseModel` 化未实施（提案建议但当前 `Dict[str, Any]` 已足，typed via docstring 字段列表）
