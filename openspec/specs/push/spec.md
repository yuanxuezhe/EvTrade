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

### REQ-PUSH-003: WS 频道 → 前端 store

- `order_update` → `client/src/stores/holdings.js:applyOrderPush` 替换 orders 中同 order_no 的项
- `trade_update` → 追加到 trades
- `position_update` → 重拉（push 当前未路由）
- `asset_update` → 重拉（push 当前未路由）
- **端点实现位置**（phase-2 拆分后）：`server/ws/endpoint.py::register_ws_endpoint(app)`，在 `server/main.py` 启动装配时调一次注册 `/ws/{channel}` 端点
  - 认证 / 接入 / 双向心跳 / 4408 timeout 关闭全部在该模块
  - ws_manager 单例由 `server/ws/manager.py` 提供（业务推送 `server/services/push_handlers.py` 也共用）

### REQ-PUSH-005: status 字段语义（v6，本地推断）

- 后端 `handle_ord_cfm` / `handle_trd_cfm` 写入 Order.status 时，**统一调用 `_infer_order_status` 本地推断**，不直接抄 broker 推送的 status
- WS `order_update` 推送的 status 字段 = DB 中的 status 字段 = 本地推断结果
- **前端契约**：
  - 前端 `inferOrderStatus(order, brokerStatus?)` 必须与后端 `_infer_order_status` **逐行一致**（同函数同输入同输出）
  - 前端 store 收到 `order_update` 时，对每条 order 调一次前端 `inferOrderStatus` 重算（防御性，避免与后端实现分叉）
  - 视图层（Trade.vue / Orders.vue）的 status 分组集合（`_PENDING_NUMERIC` / `_FILLED_NUMERIC` / `countByStatus`）必须用**后端本地推断码**：49/50/51/52/53/54/55/56（不是 broker 原始码 55/56 等）
- **后端函数位置**：`server/services/push_handlers.py:_infer_order_status`
- **前端函数位置**：`client/src/utils/format.js:inferOrderStatus`
- **v8 修订**：推断规则以 `cancelled_volume` 为主轴：
  1. 当前 status 已是终态（51/52/53/54/55/56）→ 保持
  2. `cancelled_volume >= volume` → 53（已撤）
  3. `cancelled_volume > 0 && traded_volume > 0` → 56（部成部撤）
  4. `cancelled_volume > 0`（无成交）→ 53
  5. broker_status in (52,53,54) → 撤单类信号（兼容老 broker 无 cancelled_volume 字段）
  6. 累计推断：`traded_volume` 决定 49/50/51
- **重要：WS payload status 字段可能不可信**（broker 原始 status 与本地推断码语义不一致时）。前端展示态由 `client/src/stores/holdings.js:_recomputeStatus` 统一按 `cancelled_volume + traded_volume / volume` 推断（不传 brokerStatus），详见 REQ-FE-006

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

### REQ-PUSH-010: push_handlers.py 拆分（phase-2）

378→72 行 facade 兼容垫片 + 6 个单一职责子模块：
- `server/services/order_status.py` (114) — 委托 status 共享（`ORDER_STATUS` / `TERMINAL_STATUSES` / `_status_msg` / `_infer_order_status` / `_get_active_trd_date`）
- `server/services/push_helpers.py` (34) — 4 handler 共用小工具（`_utcnow` / `_str` / `_float` / `_int`）
- `server/services/push_handler_ord.py` (81) — ord_cfm
- `server/services/push_handler_trd.py` (94) — trd_cfm
- `server/services/push_handler_pos.py` (59) — pos_cfm
- `server/services/push_handler_ast.py` (38) — ast_cfm

**契约**：
- 既有 `from services.push_handlers import ...` 仍可解析（3 import 站点全过）
  - `server/rpc/transport.py` 用 `handle_push`（在 `_run_handle_push` 内部 import）
  - `server/test_push_async.py` 用 `handle_push`
  - `server/test_push_handlers.py` 用 `handle_push` + `_infer_order_status` + `TERMINAL_STATUSES` + `_status_msg`
- 全部 4 个 handle_* 函数 + 4 共享符号 + HANDLERS dict + handle_push 都在 facade re-export
- `handle_push` 同步签名不变（向后兼容 test_push_handlers.py 11 用例 + test_push_async.py 反射测试）
- 子模块间单向依赖：push_handler_* → order_status / push_helpers；push_handlers (facade) → 全部子模块

### REQ-PUSH-008: broker ord_cfm 不匹配 cancel-row（v9）

- **背景**：v9 DELETE 端点 INSERT 撤单委托占位行（cancel-row，`order_flag=1`）。broker 协议层面不会主动推送这个 row。
- **为什么 broker 不会推**：
  - broker `ord_cfm` 的 `remark` 字段永远等于**原买单/卖单**的 `order_no`，**不会回带**我们新 cancel-row 的 `order_no`
  - 撤单 RPC `cancel_ord` 只接 `order_id`，broker 不允许本地注入自定义 remark
  - 因此 `handle_ord_cfm` 用 `remark` 匹配时永远找不到 cancel-row，cancel-row 完全不被 broker push 触及
- **后果**：cancel-row 的 `status` / `status_msg` 必须由 DELETE 端点**本地**维护（成功 → 53 / 失败 → 55），并通过 `ws_manager.broadcast` 手动推给前端
- **测试覆盖**：`server/test_push_handlers.py::test_ord_cfm_for_original_does_not_touch_cancel_row` 验证 broker 推原委托 `remark` 时 cancel-row 字段完全不被更新
- **完整 DELETE 端点契约**：见 `trading/spec.md` REQ-TRADE-003 5 步流程

### REQ-PUSH-004: 健壮性

- 解析失败的 push 消息打 warning 日志，不影响后续消息
- 未知 `func` 字段 → 忽略 + warning 日志
- WS 客户端断开时 push listener 不受影响

### REQ-PUSH-020: push 业务编排归属 services.push_dispatcher（simplify-rpc-transport-thin）

`server/services/push_dispatcher.py` 承载以下 push 业务编排职责，`server/rpc/transport.py` 不再直接承担：

- **消息解码后编排**：`PushDispatcher.dispatch(pkt, func, msg_type, wire_len)` 是 push listener 调用的单一入口；内部顺序：交互日志 → 路由查表 → 激活交易日注入 → 行迭代（调 `server.rpc.parsers_push._iter_push_rows`） → 落库（异步） → 广播（按 func 类型分派）
- **WS channel 路由表**：`_PUSH_CHANNEL = {"ord_cfm": "order_update", "trd_cfm": "trade_update", "pos_cfm": "position_update", "ast_cfm": "asset_update"}`
- **落库 helper**：`_run_handle_push(func, row, ts)` 在新线程中新建 SessionLocal + `services.push_handlers.handle_push` + commit；返回 handler 重组包结果（`Optional[Dict[str, Any]]`）
- **激活交易日注入**：`_resolve_active_trd_date_safe()` 短连接查 SysStatus 激活日；异常降级为 None 而不 raise
- **trd_cfm 双播**：`_broadcast_trade_cfm` 同时广播到 `trade_update`（成交）和 `order_update`（委托状态同步）
- **通用广播**：`_broadcast_generic` 用于 `ord_cfm` / `pos_cfm` / `ast_cfm`，用 handler 重组包结果或 fallback 行数据
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

- 🟡 `position_update` 和 `asset_update` 频道路由待完善
- 🟡 `func=qry_pos` 误路由问题根因是 QMT 端，不在本项目修复范围但需健壮处理
- 🟡 push handler `handle_pos_cfm` 不写 `market_value`（Position ORM 无此列，前端实时计算）
- 🟢 push listener 的解析器 `_parse_ord_cfm` 散落在 `client.py`，应统一为 `rpc-protocol` 能力
