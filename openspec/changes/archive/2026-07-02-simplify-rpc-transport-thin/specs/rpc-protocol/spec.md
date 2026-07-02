## MODIFIED Requirements

### Requirement: client.py 拆分（phase-2）+ transport 缩为传输骨架（simplify-rpc-transport-thin）

client.py 677→76 行 facade 兼容垫片 + 4 个单一职责子模块；transport 模块在 phase-2 后又经过一次精简（simplify-rpc-transport-thin），最终仅承担 RPClient 传输骨架：

- `server/rpc/transport.py` (~230) — RPClient 传输骨架（connect / call / reply listener / push listener 骨架）+ 全局单例 + 2 个 wire utility（`_clean_id` / `_wire_dump`）
- `server/rpc/parsers_common.py` (~109) — 通用响应解析（`_select_rs` / `_parse_code_msg` / `_iter_rows` / `_to_*` / `_empty`）
- `server/rpc/parsers_business.py` (~126) — 业务特定解析（`_parse_asset` / `_parse_orders` / `_parse_trades` / `_parse_positions` / `_parse_order_ack`）
- `server/rpc/parsers_push.py` (~30) — push 行提取（`_iter_push_rows`），与 parsers_common._iter_rows 思路不同（不做类型转换）
- `server/rpc/handlers.py` (~100) — 业务 RPC 入口（`qry_asset` / `qry_orders` / `qry_trades` / `qry_positions` / `ord_stk` / `cancel_order`）
- `server/services/push_dispatcher.py` (~200) — push 业务编排（`_run_handle_push` / `_resolve_active_trd_date_safe` / `_dispatch_push` / `_broadcast_trade_cfm` / `_broadcast_generic` / `_log_push_interaction` / `_log_push_broadcast`）+ `_PUSH_CHANNEL` 路由表；`PushDispatcher` 类

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
- **THEN** 不出现 `from server.services.*` / `from server.ws.*` / `from server.db import SessionLocal`（RELEASE 后唯一保留的 transport 内部 import 是 aio_pika / msgpacket / server.config）

### Requirement: 推送类型 → WS channel 映射表（v1，simplify-rpc-transport-thin 后归属 dispatcher）

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

## ADDED Requirements

### Requirement: transport 模块边界约束（REQ-RPC-012）

`server/rpc/transport.py` SHALL NOT 依赖以下模块（避免业务逻辑再次渗透）：

- `server.services.*`（push_handlers / push_dispatcher 之外的间接依赖通过 dispatcher 隔离）
- `server.ws.*`（ws_manager 访问由 dispatcher 持有）
- `server.db.*`（SessionLocal 创建由 dispatcher 持有）
- `server.utils.time` / `server.utils.logflow`（交互日志由 dispatcher 持有）

`transport.py` 允许的 import 范围：

- `aio_pika` / `msgpacket` — 传输协议
- `asyncio` — event loop
- `logging` — transport 自身日志（如 publisher confirm timeout）
- `server.config.settings` — 配置（RABBITMQ_URL / EXCHANGE_NAME / 队列名 / RPC_TIMEOUT）

push listener 在收到消息后 SHALL 立即调 `dispatcher.dispatch(pkt, func, msg_type, wire_len)`，不解析数据、不查询 DB、不构造 WS payload、不写交互日志。

#### Scenario: transport.py 静态边界扫描通过
- **WHEN** 用 grep 扫 `server/rpc/transport.py` 的 `from server.` import 语句
- **THEN** 仅命中 `from server.config import settings`，不命中 `server.services.*` / `server.ws.*` / `server.db.*` / `server.utils.*`

#### Scenario: push listener 不解析 push 数据
- **WHEN** push listener 收到一条 `ord_cfm` 消息
- **THEN** transport 只做三件事：解码 MsgPacket、提取 func / msg_type、调 `self._dispatcher.dispatch(...)`
- **AND** 不出现 `_iter_push_rows` / `_run_handle_push` / `_PUSH_CHANNEL` / `_log_push_*` 等业务符号