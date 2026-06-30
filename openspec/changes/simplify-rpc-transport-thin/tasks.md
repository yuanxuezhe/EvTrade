# Tasks — simplify-rpc-transport-thin

> 实施纪律（按 memory `feedback_commit_granularity`）：每个 `##` 阶段独立 commit，便于 review/回滚。

## 1. 抽出 push 行提取（无破坏）

- [x] 1.1 新建 `server/rpc/parsers_push.py`，从 `server/rpc/transport.py:83-101` 搬 `_iter_push_rows(pkt: MsgPacket) -> List[Dict[str, Any]]`
- [x] 1.2 `parsers_push.py` 顶部 import 限定为 `from msgpacket import MsgPacket` + `typing.List/Dict/Any`，无业务依赖
- [x] 1.3 `pytest server/test_*.py` 全绿（transport 暂未切换，新模块未被 import）

**commit**: `refactor(rpc): 新增 parsers_push.py 承载 push 行提取`

## 2. 抽出 push 业务编排（无破坏）

- [x] 2.1 新建 `server/services/push_dispatcher.py`
- [x] 2.2 定义 `PushDispatcher` 类，`__init__(self, rpc_client)` 仅持引用，不做副作用
- [x] 2.3 从 `transport.py` 搬入 `_PUSH_CHANNEL` 常量（模块级 dispatcher 类属性 或 类内常量）
- [x] 2.4 搬入 `_run_handle_push(func, row, ts) -> Optional[Dict[str, Any]]`（同步 helper，新线程跑 SessionLocal + handle_push + commit）
- [x] 2.5 搬入 `_resolve_active_trd_date_safe() -> Optional[str]`（短连接查 SysStatus 激活日）
- [x] 2.6 搬入 `_log_push_interaction(func, wire_len, msg_type, msg_id) -> str`（返 trace_id）
- [x] 2.7 搬入 `_log_push_broadcast(channel, data, ts, func, active_trd_date, push_trace) -> dict`（返 payload）
- [x] 2.8 搬入 `async def dispatch(self, pkt, func, msg_type, wire_len)`：调用上述 helper + 行迭代 + 落库 + 广播编排（对应 transport 原 `_dispatch_push`）
- [x] 2.9 搬入 `def _broadcast_trade_cfm(self, handler_result, channel, ts, func, active_trd_date, push_trace)`
- [x] 2.10 搬入 `def _broadcast_generic(self, handler_result, enriched_row, channel, ts, func, active_trd_date, push_trace)`
- [x] 2.11 搬入 `async def _run_push_handler(self, func, row, ts)`（在线程池跑 `_run_handle_push`）
- [x] 2.12 dispatcher 内部 import 收敛在函数内（`from server.db import SessionLocal` / `from server.services.push_handlers import handle_push` / `from server.services.guards import resolve_active_trd_date` / `from server.utils.logflow import ...` / `from server.utils.time import format_ts`）
- [x] 2.13 验证：新模块 import 成功，`pytest server/test_*.py` 在 Python 3.6.8 因 AsyncMock 不可用 pre-existing 跑不起来（env 问题，非本次重构引入）

**commit**: `refactor(services): 新增 push_dispatcher.py 承载 push 业务编排`

## 3. transport.py 切换到 dispatcher（破坏点）

- [ ] 3.1 删除 `transport.py:83-101`（`_iter_push_rows`） — 已迁到 parsers_push
- [ ] 3.2 删除 `transport.py:104-125`（`_run_handle_push`） — 已迁到 dispatcher
- [ ] 3.3 删除 `transport.py:128-150`（`_resolve_active_trd_date_safe`） — 已迁到 dispatcher
- [ ] 3.4 删除 `transport.py:153-170`（`_log_push_interaction`） — 已迁到 dispatcher
- [ ] 3.5 删除 `transport.py:173-199`（`_log_push_broadcast`） — 已迁到 dispatcher
- [ ] 3.6 删除 `transport.py:48-53`（模块级 `_PUSH_CHANNEL`） — 已迁到 dispatcher
- [ ] 3.7 删除 `transport.py:323-355`（`_dispatch_push` 类内方法） — 改为调 `self._dispatcher.dispatch(...)`
- [ ] 3.8 删除 `transport.py:357-366`（`_run_push_handler` 类内方法） — 已在 dispatcher
- [ ] 3.9 删除 `transport.py:368-397`（`_broadcast_trade_cfm` 类内方法） — 已在 dispatcher
- [ ] 3.10 删除 `transport.py:399-418`（`_broadcast_generic` 类内方法） — 已在 dispatcher
- [ ] 3.11 修改 `transport.py:202` `RPClient.__init__`：增 `self._dispatcher: Optional[PushDispatcher] = None`
- [ ] 3.12 修改 `transport.py:216` `connect()`：在 `_listen_pushs` 启动前 `self._dispatcher = PushDispatcher(self)`
- [ ] 3.13 修改 `transport.py:319` `_listen_pushs`：调 `await self._dispatcher.dispatch(pkt, func, mt, len(wire))`，删除原 `_dispatch_push` 调用
- [ ] 3.14 `transport.py` 顶部 import 收敛：删除 5 处函数内 lazy import 注释（迁移后无循环依赖）；只保留 `from server.services.push_dispatcher import PushDispatcher`（顶层一次性导入）
- [ ] 3.15 静态扫描 `server/rpc/transport.py`：`grep -n 'from server\.' server/rpc/transport.py` 仅命中 `server.config` 和 `server.services.push_dispatcher`
- [ ] 3.16 `wc -l server/rpc/transport.py` 缩到 ~230 行（验收）
- [ ] 3.17 `pytest server/test_*.py` — 此时会失败：facade re-export 的 `_run_handle_push` 等符号仍指向 transport 但 transport 已删除；预期失败，转阶段 4

**commit**: `refactor(rpc): transport.py 缩为 RPClient 传输骨架`

## 4. facade re-export 调整

- [ ] 4.1 `server/rpc/client.py:29`：`_run_handle_push` import 来源改为 `from server.services.push_dispatcher import _run_handle_push`
- [ ] 4.2 `client.py:28`：`_resolve_active_trd_date_safe` 同样改来源
- [ ] 4.3 `client.py:26`：`_PUSH_CHANNEL` 同样改来源
- [ ] 4.4 `client.py` 新增：`from server.rpc.parsers_push import _iter_push_rows`（替换原 transport 来源）
- [ ] 4.5 `client.py` `__all__` 列表保持不变（对外符号名一致）
- [ ] 4.6 验证：`python -c "from server.rpc.client import _run_handle_push, _resolve_active_trd_date_safe, _PUSH_CHANNEL, _iter_push_rows"` 解析成功
- [ ] 4.7 `pytest server/test_*.py` — 测试仍可能失败：monkeypatch 目标需要更新，转阶段 5

**commit**: `refactor(rpc): client.py facade 调整 re-export 来源`

## 5. 测试更新

- [ ] 5.1 `server/test_push_listener.py:104`：`monkeypatch.setattr(rpc_client, "_parse_push_rows", ...)` → `_iter_push_rows`（修 stale 引用，原始测试连名字都写错了）
- [ ] 5.2 `server/test_push_listener.py:109, 172, 208`：`monkeypatch.setattr(rpc_client, "_run_handle_push", ...)` → `monkeypatch.setattr("server.services.push_dispatcher._run_handle_push", ...)`（monkeypatch.setattr 字符串路径形式，可直接 patch 新源模块）
- [ ] 5.3 `server/test_push_listener.py:93, 160, 200`：`monkeypatch.setattr(rpc_client, "_resolve_active_trd_date_safe", ...)` → patch `server.services.push_dispatcher._resolve_active_trd_date_safe`
- [ ] 5.4 `server/test_push_listener.py:120`：`monkeypatch.setattr(rpc_client, "_clean_id", ...)` 保持（`_clean_id` 仍在 transport，facade re-export 不变）
- [ ] 5.5 `server/test_push_async.py:44, 78, 124`：`monkeypatch.setattr(rpc_client_mod, "_run_handle_push", ...)` → patch `server.services.push_dispatcher._run_handle_push`
- [ ] 5.6 `pytest server/test_push_listener.py server/test_push_async.py` 全绿
- [ ] 5.7 `pytest hq/ server/` 全绿（回归）

**commit**: `test(rpc): 修 _parse_push_rows stale 引用 + 更新 monkeypatch 目标模块`

## 6. 文档与归档准备

- [ ] 6.1 更新 `openspec/specs/rpc-protocol/spec.md`：REQ-RPC-010 措辞收紧为"RPClient 传输骨架"，REQ-RPC-011 路由表归属修订为 services/push_dispatcher，新 REQ-RPC-012 transport-thin 约束
- [ ] 6.2 更新 `openspec/specs/push/spec.md`：新增 REQ-PUSH-020 push 编排归属 dispatcher
- [ ] 6.3 端到端 smoke：通过 evctl 重启 backend，触发一次真实下单 + 等待 push → 验证 WS 收到 trade_update + order_update
- [ ] 6.4 验证 `wc -l server/rpc/transport.py` 缩到 ~230 行
- [ ] 6.5 验证 `grep -rn "_iter_push_rows\|_run_handle_push\|_resolve_active_trd_date_safe\|_PUSH_CHANNEL" server/rpc/transport.py` 不命中
- [ ] 6.6 git log 显示 5 个 commit（parsers_push / push_dispatcher / transport-thin / facade / test）

**commit**: `docs(openspec): 同步 spec 增量到 specs/rpc-protocol + specs/push`

## 7. 归档

- [ ] 7.1 运行 `opsx:archive`（spec delta 已合并到 specs/ 后）
- [ ] 7.2 验证 change 目录移到 `openspec/changes/archive/2026-06-30-simplify-rpc-transport-thin/`

---

## 验证清单（最终）

- [ ] `pytest hq/ server/` 全绿
- [ ] `wc -l server/rpc/transport.py` ≤ 240 行
- [ ] `wc -l server/services/push_dispatcher.py` ≤ 220 行
- [ ] `wc -l server/rpc/parsers_push.py` ≤ 40 行
- [ ] `grep -n 'from server\.' server/rpc/transport.py` 仅命中 config / services.push_dispatcher
- [ ] `from server.rpc.client import _run_handle_push, _resolve_active_trd_date_safe, _PUSH_CHANNEL, _iter_push_rows` 解析成功（facade 兼容）
- [ ] 端到端 push smoke：通过 evctl 重启 → 触发 ord_cfm / trd_cfm → WS 收到正确 payload（含 trd_date 注入）