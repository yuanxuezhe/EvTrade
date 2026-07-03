# push — 柜台主动推送 → WebSocket 路由

> 📖 **字段映射**详见 [`data-model/spec.md`](../data-model/spec.md) §1（落库字段）

## Purpose

QMT 柜台通过 RabbitMQ 主动推送（`EvTrade.Test.Push` 队列）异步通知状态变化。
后端 RPC 客户端必须把这些 push 消息按事件类型路由到对应的 WebSocket 频道。

## Requirements

### REQ-PUSH-001: 监听 Push 队列

- RPC 客户端 `start()` 时启动 push listener
- 队列名：`EVTRADE_QUEUE_PUSH`（默认 `EvTrade.Test.Push`）
- 收到消息后根据 `func` 字段判断事件类型

### REQ-PUSH-002: 事件路由

| Func 字段 | 事件 | 路由到 WS 频道 | 前端处理 |
|---|---|---|---|
| `ord_cfm` | 委托状态变更/成交 | `order_update` | 替换 store 中同 order_no 的项；**status 字段是后端本地推断结果**（见 REQ-PUSH-005） |
| `trd_cfm` | 成交回报 | `trade_update` | 追加到 trades 列表 |
| `qry_pos` 等查询响应 | ❌ **不应在 push 出现** | — | 忽略，**应被 reply 队列消费** |
| ~~`pos_cfm`~~ | ❌ broker 不发 | — | consolidate-position-data-flow: 已删除 |
| ~~`ast_cfm`~~ | ❌ broker 不发 | — | consolidate-position-data-flow: 已删除 |

### REQ-PUSH-003: WS 频道 → 前端 store

- `order_update` → `client/src/stores/holdings.js:applyOrderPush` 替换 orders 中同 order_no 的项
- `trade_update` → 追加到 trades
- ~~`position_update`~~ → consolidate-position-data-flow: 频道已删除（broker 不发 pos_cfm）
- ~~`asset_update`~~ → consolidate-position-data-flow: 频道已删除（broker 不发 ast_cfm）
- **端点实现位置**（phase-2 拆分后）：`server/ws/endpoint.py::register_ws_endpoint(app)`，在 `server/main.py` 启动装配时调一次注册 `/ws/{channel}` 端点
  - 认证 / 接入 / 双向心跳 / 4408 timeout 关闭全部在该模块
  - ws_manager 单例由 `server/ws/manager.py` 提供（业务推送 `server/services/push_handlers.py` 也共用）

### REQ-PUSH-005: status 字段语义（v11 broker 字典对齐）

后端写入 Order.status 时 MUST 采用 broker xtconstant 字典（11 条: 48-57 + 255），无本地扩展。`handle_ord_cfm` 直接采用 broker 推回；`handle_trd_cfm` 累计后调 `_infer_order_status` 推断输出码全集 {50, 53, 54, 55, 56}（全是 broker 码）。

#### Scenario: handle_trd_cfm 推断终态采用 broker 码

- **WHEN** Order.volume=100, traded_volume=50（部成）, handle_trd_cfm 累计后调 _infer_order_status
- **THEN** 输出 status='55'（broker 部成），不是本地推断码 50

#### Scenario: handle_ord_cfm broker 推回直接采用

- **WHEN** broker ord_cfm 推回 order_status='54'（broker 已撤）
- **THEN** handle_ord_cfm 直接采用 Order.status='54'，不再翻译

#### Scenario: 终态保持（含 broker 52）

- **WHEN** Order.status='52'（broker 部成待撤）或 '53'/'54'/'55'/'56'/'57'
- **THEN** handle_trd_cfm 累计后调 _infer_order_status 不覆盖该 status

#### Scenario: 业务写入点 broker 码（v9 cancel-row 短路）

- **WHEN** DELETE 端点 INSERT cancel-row (order_flag=1)
- **THEN** cancel-row.status 起手 '48'（本地 sentinel）
- **AND** DELETE 成功 → '54'（broker 已撤）
- **AND** DELETE 失败 → '57'（broker 废单）

#### Scenario: _infer_order_status 输出 broker 码

- **WHEN** _infer_order_status 推断终态
- **THEN** 输出码全集 {50, 53, 54, 55, 56}（全是 broker 码）
- **AND** broker_status 撤单类判定 `('52','53','54')` 不变（broker 码与本地巧合对齐）

- WS `order_update` 推送的 status 字段 = DB 中的 status 字段 = broker 码（v11 起）
- **前端契约**：
  - 前端 `inferOrderStatus(order, brokerStatus?)` 必须与后端 `_infer_order_status` **逐行一致**，输出 broker 码
  - 前端 store 收到 `order_update` 时，对每条 order 调一次前端 `inferOrderStatus` 重算（防御性，避免与后端实现分叉）
  - 视图层（Trade.vue / Orders.vue）的 status 分组集合（`_PENDING_NUMERIC` / `_FILLED_NUMERIC` / `countByStatus`）必须用**broker xtconstant 字典**：48/49/50/51/52/53/54/55/56/255（v11 起）
- **后端函数位置**：`server/services/push_handlers.py:_infer_order_status`
- **前端函数位置**：`client/src/utils/format.js:inferOrderStatus`
- **v11 broker 字典对齐**：订单/成交状态码全部采用 broker xtconstant 字典（48-57 + 255），无本地扩展
- **v8 修订**（历史保留）：推断规则以 `cancelled_volume` 为主轴
  1. 当前 status 已是终态（broker 52/53/54/55/56/57）→ 保持
  2. `cancelled_volume >= volume` → 54（broker 已撤）
  3. `cancelled_volume > 0 && traded_volume > 0` → 53（broker 部成部撤）
  4. `cancelled_volume > 0`（无成交）→ 54
  5. broker_status in (51,52,53,54) → 撤单类信号（broker 码）
  6. 累计推断：`traded_volume` 决定 50/51
- **v11 历史**：旧本地推断码（49/50/51/52/53/54/55/56）已废弃；前端展示态由 `client/src/stores/holdings.js:_recomputeStatus` 统一按 `cancelled_volume + traded_volume / volume` 推断，输出 broker 码，详见 REQ-FE-006

### REQ-PUSH-006: 异步落库（v8）

- push listener 调用 `handle_push(db, func, row, ts)` 时，**必须**走 `asyncio.to_thread(...)` 包裹，**禁止**在 event loop 中直接同步执行 SQLAlchemy
- 原因：push 消息密集到达时同步 SQL 操作阻塞 event loop，导致 reply 队列消费延迟、WebSocket 推送卡顿
- 实现：push listener 内部用 `await asyncio.to_thread(_run_handle_push, func, row, ts)`，helper 在新线程中新建 SessionLocal + handle_push + commit
- 错误处理：to_thread 内异常被 listener 捕获，打 error 日志（已存在），**不重试**（broker 推过的消息不会再来）
- 向后兼容：`handle_push` 同步签名不变，test_push_handlers.py 现有 11 用例继续通过

### REQ-PUSH-007: 推送按 (activeTrdDate, order_no) 匹配（v8）

#### 权威日注入（后端）

- **唯一权威**：`server/api/system.py::GET /api/system/active-day` 返激活交易日
  - 查 `SysStatus` 表 `status='active'` 的 `trd_date`
  - 响应 `{code: 0, msg: "ok", list: [{trd_date: "YYYYMMDD", status: "active"}]}`，拦截器解包后 `data[0].trd_date`
  - **不**复用 `/api/trading/clock`（flat object，非 RPC 风格）
- `server/rpc/client.py::_listen_pushs` 在 broadcast 前，用权威日**覆盖** broker 推的 trd_date（broker 偶尔推隔夜老委托）
  - `_resolve_active_trd_date_safe` 短连接 helper：动态导入 `from db import SessionLocal`，异常降级为 None
  - 注入位置：payload.data（在 broadcast 之前）+ 持久化 row（在 handle_push 之前）
  - **None 降级**：helper 异常不中断 push 链路

#### 前端守门

- `client/src/stores/holdings.js::applyOrderPush/applyTradePush` 在 merge 前校验：
  - `if (activeTrdDate.value && row.trd_date && row.trd_date !== activeTrdDate.value) return`
  - 缺 `row.trd_date`（broker 旧版本透传字段名不同）放行，**只拒绝明确的非激活日**
- `activeTrdDate` 在 `bootstrap` 第 1 步拉，失败降级为 null（push 守门不拦）
- **匹配键**：`order_no`，WS payload 兜底 `row.order_no || row.remark`（v6 `order-pk-by-orderno` 决定）

详见归档 `archive/2026-06-21-order-push-trd-date-authority/spec-deltas/push.md`

### REQ-PUSH-010: push_handlers.py 拆分（phase-2，consolidate-position-data-flow 修订）

378→72 行 facade 兼容垫片 + 4 个单一职责子模块（consolidate-position-data-flow 删 pos/ast）：
- `server/services/order_status.py` (114) — 委托 status 共享（`ORDER_STATUS` / `TERMINAL_STATUSES` / `_status_msg` / `_infer_order_status` / `_get_active_trd_date`）
- `server/services/push_helpers.py` (34) — 2 handler 共用小工具（`_utcnow` / `_str` / `_float` / `_int`）
- `server/services/push_handler_ord.py` (81) — ord_cfm
- `server/services/push_handler_trd.py` (94) — trd_cfm（含 consolidate-position-data-flow Position.vol 增量更新）

**契约**：
- 既有 `from services.push_handlers import ...` 仍可解析（3 import 站点全过）
  - `server/rpc/transport.py` 用 `handle_push`（在 `_run_handle_push` 内部 import）
  - `server/test_push_async.py` 用 `handle_push`
  - `server/test_push_handlers.py` 用 `handle_push` + `_infer_order_status` + `TERMINAL_STATUSES` + `_status_msg`
- 全部 2 个 handle_* 函数 + 4 共享符号 + HANDLERS dict + handle_push 都在 facade re-export
- `handle_push` 同步签名不变（向后兼容 test_push_handlers.py 用例 + test_push_async.py 反射测试）
- 子模块间单向依赖：push_handler_* → order_status / push_helpers；push_handlers (facade) → 全部子模块

### REQ-PUSH-008: broker ord_cfm 不匹配 cancel-row（v9，v11 broker 码）

- **背景**：v9 DELETE 端点 INSERT 撤单委托占位行（cancel-row，`order_flag=1`）。broker 协议层面不会主动推送这个 row。
- **为什么 broker 不会推**：
  - broker `ord_cfm` 的 `remark` 字段永远等于**原买单/卖单**的 `order_no`，**不会回带**我们新 cancel-row 的 `order_no`
  - 撤单 RPC `cancel_ord` 只接 `order_id`，broker 不允许本地注入自定义 remark
  - 因此 `handle_ord_cfm` 用 `remark` 匹配时永远找不到 cancel-row，cancel-row 完全不被 broker push 触及
- **后果**：cancel-row 的 `status` / `status_msg` 必须由 DELETE 端点**本地**维护（v11 broker 码：成功 → 54 / 失败 → 57），并通过 `ws_manager.broadcast` 手动推给前端
- **v11 broker 字段映射补遗**：`broker ord_cfm` 不匹配 cancel-row 的判断条件中 `status` 字段值 MUST 是 broker 码；cancel-row 自身 status 由 DELETE 端点维护

#### Scenario: cancel-row status 由 DELETE 端点维护（v11 修订）

- **WHEN** DELETE 端点 INSERT cancel-row (order_flag=1)
- **THEN** cancel-row.status 起手 '48'（broker UNREPORTED 本地 sentinel）
- **AND** DELETE 成功 → '54'（broker CANCELED 已撤）
- **AND** DELETE 失败 → '57'（broker JUNK 废单）
- **AND** WS broadcast payload 含 status='54' 或 '57', 前端 view 按 broker 字典解读

- **测试覆盖**：`server/test_push_handlers.py::test_ord_cfm_for_original_does_not_touch_cancel_row` 验证 broker 推原委托 `remark` 时 cancel-row 字段完全不被更新
- **完整 DELETE 端点契约**：见 `trading/spec.md` REQ-TRADE-003 5 步流程

### REQ-PUSH-004: 健壮性

- 解析失败的 push 消息打 warning 日志，不影响后续消息
- 未知 `func` 字段 → 忽略 + warning 日志
- WS 客户端断开时 push listener 不受影响

### REQ-PUSH-020: push 业务编排归属 services.push_dispatcher（simplify-rpc-transport-thin）

`server/services/push_dispatcher.py` 承载以下 push 业务编排职责，`server/rpc/transport.py` 不再直接承担：

- **消息解码后编排**：`PushDispatcher.dispatch(pkt, func, msg_type, wire_len)` 是 push listener 调用的单一入口；内部顺序：交互日志 → 路由查表 → 激活交易日注入 → 行迭代（调 `server.rpc.parsers_push._iter_push_rows`） → 落库（异步） → 广播（按 func 类型分派）
- **WS channel 路由表**：`_PUSH_CHANNEL = {"ord_cfm": "order_update", "trd_cfm": "trade_update"}`（consolidate-position-data-flow: pos_cfm / ast_cfm 已删除）
- **落库 helper**：`_run_handle_push(func, row, ts)` 在新线程中新建 SessionLocal + `services.push_handlers.handle_push` + commit；返回 handler 重组包结果（`Optional[Dict[str, Any]]`）
- **激活交易日注入**：`_resolve_active_trd_date_safe()` 短连接查 SysStatus 激活日；异常降级为 None 而不 raise
- **trd_cfm 双播**：`_broadcast_trade_cfm` 同时广播到 `trade_update`（成交）和 `order_update`（委托状态同步）
- **通用广播**：`_broadcast_generic` 用于 `ord_cfm`，用 handler 重组包结果或 fallback 行数据（consolidate-position-data-flow: pos_cfm / ast_cfm 已删除）
- **push 交互日志**：`_log_push_interaction` 记 `[svc<-rpc] push` + `_log_push_broadcast` 记 `[svc->front] ws broadcast (push)`

`RPClient` 在 `connect()` 时构造 `self._dispatcher = PushDispatcher(self)`（self 注入用于 dispatcher 拿 RPClient 引用，如需扩展）。

依赖方向（无环）：

```
PushDispatcher
  ├─▶ services.push_handlers.handle_push
  ├─▶ services.guards.resolve_active_trd_date
  ├─▶ ws_manager.broadcast
  ├─▶ utils.logflow.log_interaction
  └─▶ utils.time.format_ts
```

#### Scenario: trd_cfm 同时广播 trade_update + order_update
- **WHEN** dispatcher.dispatch(pkt, func="trd_cfm", ...) 收到 1 行成交回报
- **AND** handler 返回 `{"trade": TradeOut, "order": OrderOut}`
- **THEN** ws_manager.broadcast("trade_update", trade_payload) 被调用 1 次
- **AND** ws_manager.broadcast("order_update", order_payload) 被调用 1 次
- **AND** 两次广播使用同一 trace_id（来自 msg_id 或自动生成 UUID）

#### Scenario: 未知 func 不广播
- **WHEN** dispatcher.dispatch(pkt, func="unknown_cfm", ...)
- **THEN** 打 warning 日志（`RPClient.push ignore unknown func=%r`）
- **AND** 不调用 handle_push / ws_manager.broadcast
- **AND** transport listener 继续消费下一条消息（不抛异常）

#### Scenario: handler 抛错不中断广播链路
- **WHEN** dispatcher.dispatch 调用 `_run_handle_push` 时 handle_push 抛 RuntimeError
- **THEN** 异常被 listener 捕获，打 error 日志
- **AND** `_PUSH_CHANNEL.get(func)` 仍返回有效 channel 时仍执行 broadcast（用 fallback 行数据）
- **AND** 后续 push 消息继续处理（listener 不退出）

#### Scenario: 激活日查询异常降级
- **WHEN** `_resolve_active_trd_date_safe()` 因 DB 锁 / disconnect 抛异常
- **THEN** 返回 None 而不 raise
- **AND** dispatcher 不把 `trd_date` 注入 payload.data / 持久化 row
- **AND** 前端 `_today_yyyymmdd` 兜底（已有契约）

#### Scenario: transport 不持有 push 业务符号
- **WHEN** 静态扫 `server/rpc/transport.py`
- **THEN** 不出现 `_iter_push_rows` / `_run_handle_push` / `_resolve_active_trd_date_safe` / `_dispatch_push` / `_broadcast_trade_cfm` / `_broadcast_generic` / `_log_push_interaction` / `_log_push_broadcast` / `_PUSH_CHANNEL`
- **AND** 仅出现 `self._dispatcher.dispatch(...)` 一处调用

### REQ-PUSH-030: push handler 字段映射表（v10 broker 原字段名，rpc-field-alignment-ts-unify 实施）

push handler MUST 严格读 broker 原字段名（snake_case），与 parsers 层对齐；DB 字段映射由 push handler 内部显式完成，禁止在 handler 内部做字段名 alias / 兼容映射（避免与 parsers 双源不一致）。

#### ord_cfm 字段映射

| broker 字段（xtquant 协议） | server 字段 | 备注 |
|---|---|---|
| `order_id` | `Order.order_id` | 柜台真实委托号 |
| `stock_code` | 透传 | 不写库（Order 已有） |
| `order_status` | 喂给 `_infer_order_status` | broker 原字段名，**不 alias `status`** |
| `order_volume` | `Order.volume` 覆盖 | broker 改单后真实 volume |
| `traded_volume` | **不写**（trd_cfm 累计） | v6 决策 |
| `price` / `traded_price` | **不写** | trd_cfm 累计算 avg |
| `strategy_name` | 透传 | 暂不入库 |
| `remark` | 匹配本地 Order | broker 透传回来的 order_no |
| `order_time` | `Order.order_time` | v10 起写库（标准格式 23 字符） |
| `cancelled_volume` / `cancel_volume` / `withdrawn_volume` | `Order.cancelled_volume` 累加 | v8 决策，多字段名兼容 |

#### trd_cfm 字段映射

| broker 字段（xtquant 协议） | server 字段 | 备注 |
|---|---|---|
| `traded_id` | `Trade.trade_id` | broker 原字段名（**不 alias `trade_id`**） |
| `order_id` | 兜底定位 Order | broker 真实委托号 |
| `remark` | 匹配本地 Order | broker 透传回来的 order_no |
| `stock_code` | `Trade.stock_code` | |
| `order_type` | `Trade.order_type` | 23/24 |
| `traded_price` | `Trade.price` | broker 原字段名（**不 alias `price`**） |
| `traded_volume` | `Trade.volume` | broker 原字段名（**不 alias `volume`**） |
| `traded_amount` | `Trade.amount` | broker 原字段名（**不 alias `amount`**） |
| `traded_time` | `Trade.trade_time` | broker 原字段名（**不 alias `trade_time`**） |
| `trade_type` | `Trade.trade_type` | consolidate-position-data-flow: 0=normal 1=cancel-fill |
| `account_id` | 透传 | 暂不入库 |
| `strategy_name` | 透传 | 暂不入库 |

#### Scenario: push handler 字段名严格匹配 broker

- **WHEN** broker 推送 `trd_cfm` row 含 `traded_id` / `traded_volume` / `traded_price` / `traded_amount` / `traded_time`
- **THEN** `push_handler_trd.py` MUST 直接读 broker 原字段名（`row.get('traded_id')` 等），不允许 alias 兼容（`row.get('traded_id') or row.get('trade_id')`）
- **AND** 与 `parsers_business.py::_parse_trades` 字段名一致

#### Scenario: 旧 alias 字段已废弃

- **WHEN** developer 在 push handler 中写 `row.get('trade_id')`（老 alias）
- **THEN** code review MUST 拒收；正确写法为 `row.get('traded_id')`

### REQ-PUSH-030: broker status 字段重映射表（v11 新增段）

push handler MUST 严格读 broker 原字段名（snake_case），与 parsers 层对齐；WS payload `status` 字段 MUST 是 broker xtconstant 数字字符串 (`'48'`...`'255'`)，含义与 xtconstant 字典一一对应。

#### Scenario: WS payload status 字段是 broker 码（v11 新增）

- **WHEN** WS `order_update` payload 含 status 字段
- **THEN** status 字段值必须是 broker xtconstant 字典之一 (48/49/50/51/52/53/54/55/56/57/255)
- **AND** 前端 view (Trade.vue / Orders.vue) 的 status 分组集合按 broker 字典定义
- **AND** 不再有"本地推断码"语义层 (旧本地码 49/50/51/53/56 全部对齐到 broker 码)

### REQ-PUSH-031: trd_cfm 触发 Position.vol 增量更新（consolidate-position-data-flow）

broker 推 `trd_cfm` 时,后端在落库 Order / Trade 的同时 MUST 同步更新对应 stock_code 的 `Position.vol` 字段（intra-day 实时性）。增量更新仅作用于 `vol` 字段；`cost_price` / `avl_vol` / `today_buy` / `today_sell` / `last_vol` 等由 day-init reconcile 兜底不动。

#### Scenario: 买单成交 → Position.vol 增加

- **WHEN** broker 推 trd_cfm, order_type='23'（买）, volume=100, stock_code='600030.SH'
- **AND** Position row 存在（`stock_code='600030.SH'` 已由 day-init reconcile 创建）
- **THEN** `Position.vol` += 100
- **AND** `Position.cost_price` / `Position.avl_vol` / `Position.last_vol` 等其他字段不变

#### Scenario: 卖单成交 → Position.vol 减少

- **WHEN** broker 推 trd_cfm, order_type='24'（卖）, volume=50
- **AND** Position row 存在
- **THEN** `Position.vol` -= 50
- **AND** 其他字段不变

#### Scenario: Position 不存在 → log warning 跳过

- **WHEN** broker 推 trd_cfm 且对应 stock_code 的 Position row 不存在（e.g. day-init reconcile 未跑）
- **THEN** `handle_trd_cfm` MUST log 一条 WARNING（含 order_no / trade_id / stock_code）并跳过 Position.vol 更新
- **AND** Order / Trade 落库照常进行（不阻塞成交写入）

#### Scenario: cancel-trade (trade_type=1) → 必须跳过 Position 更新

- **WHEN** broker 推 trade_type=1（cancel-trade, user_def='CANCEL:orig_order_no'）的 trd_cfm
- **THEN** `handle_trd_cfm` MUST 跳过 Position.vol ±volume 逻辑（按 OQ-1 选项 B 决议：DELETE 端点已抹平 `orig.cancelled_volume = orig.volume`，cancel-trade 是状态变更声明而非新增交易）
- **AND** `Position.vol` / `Position.cost_price` 等其他字段保持不变
- **AND** Order / Trade 落库照常进行（cancel-trade 走与正常 trd_cfm 相同的 ORM 写入路径）

### REQ-PUSH-032: pos_cfm / ast_cfm 删除（BREAKING，consolidate-position-data-flow）

broker xtquant 协议不发送 `pos_cfm` 与 `ast_cfm` 推送事件（xtquant 推送仅有 `ord_cfm` 与 `trd_cfm` 两个 func 名）。本 MUST 删除所有 `pos_cfm` / `ast_cfm` 路由、handler 文件、WS 频道与前端 store 入口；`pos_cfm` / `ast_cfm` MUST NOT 注册到任何 `_PUSH_CHANNEL` 或 `HANDLERS` dict 中。持仓 / 资金的实时性改由 `trd_cfm → Position.vol` 增量（持仓层，REQ-PUSH-031）+ day-init reconcile（权威快照）共同满足。

#### Scenario: pos_cfm 不再有任何路由/handler/频道

- **WHEN** broker 意外推送 func='pos_cfm' 消息
- **THEN** push listener MUST log INFO 级别忽略（do not route）
- **AND** `server/services/push/pos.py` 文件不存在
- **AND** `server/services/push/routes.py::_PUSH_CHANNEL` 中无 `pos_cfm` 键
- **AND** `server/services/push/handlers.py::HANDLERS` 中无 `pos_cfm` 入口
- **AND** WS 频道不存在 `position_update` 端点

#### Scenario: ast_cfm 不再有任何路由/handler/频道

- **WHEN** broker 意外推送 func='ast_cfm' 消息
- **THEN** push listener MUST log INFO 级别忽略
- **AND** `server/services/push/ast.py` 文件不存在
- **AND** `server/services/push/routes.py::_PUSH_CHANNEL` 中无 `ast_cfm` 键
- **AND** `server/services/push/handlers.py::HANDLERS` 中无 `ast_cfm` 入口
- **AND** WS 频道不存在 `asset_update` 端点

#### Scenario: 前端 store 移除 pos/ast push 入口

- **WHEN** 前端 store 模块加载
- **THEN** `client/src/stores/ws_dispatch.js` 中不存在 `_onPositionCfm` / `_onAssetCfm` 函数
- **AND** `dispatchPayload` switch 中不存在 `pos_cfm` / `ast_cfm` case
- **AND** `client/src/stores/holdings_push.js` 中不存在 `applyPositionPush` / `applyAssetPush` 函数
- **AND** `client/src/stores/holdings.js` 不 re-export 这些函数

### REQ-PUSH-033: WS 频道列表（consolidate-position-data-flow 变更后清单）

变更后 WebSocket MUST 仅推送 `order_update`（来自 ord_cfm）与 `trade_update`（来自 trd_cfm）两个频道。`position_update` / `asset_update` 频道 MUST NOT 注册到 `server/ws/manager.py`，**不再存在**。

#### Scenario: 前端依赖 position_update / asset_update 需迁移

- **WHEN** 前端代码或外部集成曾订阅 `position_update` 或 `asset_update` 频道
- **THEN** 该订阅将永远收不到消息（服务端断流）
- **AND** **BREAKING**: 调用方必须迁移为轮询 `/api/holdings`（持仓）与 `/api/asset`（资金）
- **AND** 持仓数量变化 → 通过 Order.status（broker 已报/已成交）推 `order_update` 反查持仓是否变化

## Scenarios

### S-PUSH-001: 成交回报

Given 委托 12345 部分成交 100 股 @ 12.34  
When 柜台 push `trd_cfm` 消息  
Then 后端解析后 push 到 WS 频道 `trade_update`  
And 前端 `trades` store 追加 `{trade_id, order_id, stock_code, volume:100, price:12.34, ...}`

### S-PUSH-002: 委托状态变更（本地推断后）

Given Order 初始 `volume=100, traded_volume=0, status="49"`
When 柜台 push `trd_cfm` `{order_id:"12345", volume:50}`（累计 50/100）
Then 后端 `handle_trd_cfm` 累加 `traded_volume=50` 并调 `_infer_order_status` → `status="50"`（部成）
And WS 频道 `order_update` 推 `{order_no:"...", status:"50", traded_volume:50, ...}`（**50 是本地推断码，不是 broker 码**）
And 前端 store 替换 orders 中同 order_no 的项；前端 store 调前端 `inferOrderStatus` 防御性重算确认 `status="50"`

### S-PUSH-003: Push 误路由到 qry_pos

⚠️ **已知问题**：QMT 端有时把 ord_cfm 路由到 `qry_pos` 队列名  
Then 解析时只有 `{code, msg}` 字段，没有 stock_code/evt_type  
Action: 打 warning 日志，**不重派**（避免循环）

### S-PUSH-004: push 落库不阻塞 event loop（v8）

Given push listener 收到 1 条 `ord_cfm`（handle_push 内部 SQLAlchemy 同步操作 50ms）  
When 主线程同时处理 1 个 RPC reply（0.5ms 应答）  
Then reply 消费延迟 < 5ms（不被 push 阻塞）  
And `handle_push` 在子线程执行（to_thread 包裹）

## Push 消息结构

```
func=ord_cfm
RS1: [{code: 0, msg: ""}]
RS2: [{
    order_id: "...",
    stock_code: "...",
    order_type: "23"|"24",
    volume: ...,
    price: ...,
    price_type: ...,
    status: "48"-"57"|"255",
    traded_volume: ...,
    traded_price: ...,
    order_time: "HH:MM:SS",
    remark: "..."        # v5: 柜台透传字段 (= 本地 order_no)
    status_msg: "..."    # 废单原因 / 撤单原因
}]
```

**v5 匹配规则**：`handle_ord_cfm` 先按 `order_id` 匹配本地 Order；未命中再用 `remark` (= `order_no`) 兜底匹配（应对 broker 端重新生成 `order_id` 但透传 `remark` 不变的场景）。

**v7 落库调整**（`handle_trd_cfm`）：
- 落 `Trade` 时**不再写 `order_id`**（broker 号在成交回报到达时可能尚未到达）
- 用 `order_no`（解析 `remark` 字段得到）作为 Trade PK 第二段（PK = `(trd_date, order_no, trade_id)`）
- 若 `remark` 解析失败 → 打 warning 日志，跳过该条成交（不要让一条缺关联的成交写入）

## Known Issues (from analysis)

- ✅ consolidate-position-data-flow: `pos_cfm` / `ast_cfm` / `position_update` / `asset_update` 已删除（REQs 032/033），handler dead code 清除
- 🟡 `func=qry_pos` 误路由问题根因是 QMT 端，不在本项目修复范围但需健壮处理
- 🟢 push listener 的解析器 `_parse_ord_cfm` 散落在 `client.py`，应统一为 `rpc-protocol` 能力
