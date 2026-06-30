## ADDED Requirements

### Requirement: push 业务编排归属 services.push_dispatcher（REQ-PUSH-020）

`server/services/push_dispatcher.py` 承载以下 push 业务编排职责，`server/rpc/transport.py` 不再直接承担：

- **消息解码后编排**：`PushDispatcher.dispatch(pkt, func, msg_type, wire_len)` 是 push listener 调用的单一入口；内部顺序：交互日志 → 路由查表 → 激活交易日注入 → 行迭代 → 落库（异步）→ 广播（按 func 类型分派）
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