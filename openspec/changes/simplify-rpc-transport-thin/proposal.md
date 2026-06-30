## Why

`server/rpc/transport.py` 当前 602 行，单一模块同时承担 6 类职责（传输层 / push 业务编排 / DB session helper / 交易日查询 / 交互日志 / WS 广播），与 `rpc-protocol/REQ-RPC-010` 的"RPClient 传输层"定义严重脱节。最近两次重构（`8d79bd4` push 重组包、`960c6a9` `_listen_pushs` 拆分）只是把 push 编排拆成更多方法，净增 81 行——文件越拆越长，根因（业务逻辑渗透到传输层）未解决。transport 模块对外既被 facade re-export 4 个业务 helper（`_PUSH_CHANNEL` / `_run_handle_push` / `_resolve_active_trd_date_safe` / `_iter_push_rows`），又被 `test_push_listener.py` / `test_push_async.py` 用 monkeypatch 直接戳进内部，单测需要起 RabbitMQ + mock DB + mock ws_manager 才能跑通。

## What Changes

- 新增 `server/services/push_dispatcher.py`：承载 push 业务编排（`_dispatch_push` / `_broadcast_trade_cfm` / `_broadcast_generic` / `_run_push_handler` / `_run_handle_push` / `_resolve_active_trd_date_safe` / `_log_push_interaction` / `_log_push_broadcast`）和 `_PUSH_CHANNEL` 路由表
- 新增 `server/rpc/parsers_push.py`：承载 push 行提取 `_iter_push_rows`
- 精简 `server/rpc/transport.py`：仅保留 `RPClient`（connect / close / call / reply listener / push listener 骨架）+ 全局单例 + `_clean_id` / `_wire_dump` 两个 wire utility，估算 ~230 行
- 调整 `server/rpc/client.py` facade re-export：4 个 push 业务 helper 改从 `services.push_dispatcher` 和 `parsers_push` import
- 更新 `server/test_push_listener.py`（修掉 stale 的 `_parse_push_rows` 引用 + 调整 monkeypatch 目标模块）+ `server/test_push_async.py`（monkeypatch 目标从 `rpc_client` 改为 facade re-export 的新源模块）
- 更新 `openspec/specs/rpc-protocol/spec.md`：REQ-RPC-010 措辞收紧 + REQ-RPC-011 路由表归属修订 + 新增 REQ-RPC-012 transport-thin
- 更新 `openspec/specs/push/spec.md`：新增 REQ-PUSH-020 明确 push 编排归属

**BREAKING**: 无对外 API 变更；模块内部符号全部由 facade re-export 保证向后兼容。

## Capabilities

### New Capabilities

（无 — push 编排属于 push 能力内部结构调整，不引入新能力）

### Modified Capabilities

- `rpc-protocol`: REQ-RPC-010 措辞收紧为"RPClient 传输骨架"，REQ-RPC-011 路由表归属从 transport 改为 services/push_dispatcher，新增 REQ-RPC-012 禁止 transport 依赖 services/ws/db
- `push`: 新增 REQ-PUSH-020 明确 push 编排归属 services/push_dispatcher，push listener 与 dispatcher 的协作契约

## Impact

| 文件 | 改动 |
|---|---|
| `server/rpc/transport.py` | 删除 8 个 push helper + 4 个 push 类内方法 → 从 ~602 缩到 ~230 |
| `server/rpc/parsers_push.py` | 新增 ~30 行 |
| `server/services/push_dispatcher.py` | 新增 ~200 行 |
| `server/rpc/client.py` | re-export 来源调整（约 5 行变更） |
| `server/test_push_listener.py` | 修 `_parse_push_rows` stale 引用 + monkeypatch 目标调整 |
| `server/test_push_async.py` | monkeypatch 目标调整 |
| `openspec/specs/rpc-protocol/spec.md` | REQ-RPC-010 / REQ-RPC-011 修订 + REQ-RPC-012 新增 |
| `openspec/specs/push/spec.md` | REQ-PUSH-020 新增 |

**依赖方向**（拆分后）：

```
transport ──(callback)──▶ services/push_dispatcher
   │                              │
   │                              ▼
   │                       services.push_handlers
   │                       services.guards
   │                       ws_manager
   ▼
handlers (业务 RPC，不动)
```

无循环依赖；transport.py 删除 5 处函数内 lazy import（`from server.db` / `from server.utils.logflow` / `from server.services.push_handlers` / `from server.utils.time` / `from server.services.guards`）—— 这些本就是模块边界错的信号。

**commit 拆分**（按 memory `feedback_commit_granularity`）：

1. `refactor(rpc): 新增 parsers_push.py 承载 push 行提取`
2. `refactor(services): 新增 push_dispatcher.py 承载 push 业务编排`
3. `refactor(rpc): transport.py 缩为 RPClient 传输骨架`
4. `refactor(rpc): client.py facade 调整 re-export 来源`
5. `test(rpc): 修 _parse_push_rows stale 引用 + 更新 monkeypatch 目标`
6. `docs(openspec): 同步 spec 增量到 specs/`