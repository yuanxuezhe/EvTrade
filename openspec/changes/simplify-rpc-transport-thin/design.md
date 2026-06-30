## Context

`server/rpc/transport.py` 在 phase-2 拆分（commit `e5c3f4b`）时把原 677 行的 `client.py` 拆成 transport / parsers / handlers 4 个子模块，但 push 业务编排（`_listen_pushs` + `_dispatch_push` + `_broadcast_*` + `_run_handle_push` + `_resolve_active_trd_date_safe` + `_iter_push_rows` + `_log_push_*`）全部留在 transport。后续 `8d79bd4`（push 重组包）和 `960c6a9`（_listen_pushs 再拆分）两次重构都只在该文件内部增加方法，没有把业务逻辑迁出。

当前 transport.py 的实际依赖图（5 处函数内 lazy import 是模块边界错的信号）：

```
transport.py
  ├─ aio_pika / msgpacket        ← 真正的传输依赖
  ├─ server.config.settings      ← 配置
  ├─ server.ws.manager           ← 业务（应为依赖反向）
  ├─ server.db (lazy)            ← 业务（应为依赖反向）
  ├─ server.services.push_handlers (lazy) ← 业务
  ├─ server.services.guards (lazy)        ← 业务
  ├─ server.utils.logflow (lazy) ← 日志
  └─ server.utils.time (lazy)    ← 业务
```

`client.py` facade 不得不 re-export 4 个业务符号（`_PUSH_CHANNEL` / `_run_handle_push` / `_resolve_active_trd_date_safe` / `_iter_push_rows`），暴露出 facade 边界本身已经模糊。

## Goals / Non-Goals

**Goals:**

- transport.py 回归"RPClient 传输骨架 + 单例 + wire utility"，估算 ~230 行
- push 业务编排整体迁出到 `services/push_dispatcher.py`，单一职责
- 解除 transport.py 对 `server.services.*` / `server.ws.*` / `server.db.*` 的依赖
- 单测可在不连 RabbitMQ 的前提下覆盖 dispatcher 的 4 个 broadcast 分支
- facade `client.py` 行为不变（13 import 站点零改动）
- 测试零回归（`pytest hq/ server/` 全绿）

**Non-Goals:**

- 不修改 push 业务行为（落库字段、WS payload 结构、trd_date 注入时机）—— 纯结构搬迁
- 不引入新依赖、不升级 aio_pika / msgpacket
- 不修改其他 4 个 push 子模块（`services/push_handler_ord.py` / `push_handler_trd.py` / `push_handler_pos.py` / `push_handler_ast.py`）—— REQ-PUSH-010 已定的契约保持稳定
- 不合并 parsers_push.py 到 parsers_common.py（行提取不做类型转换的语义差异要保留）

## Decisions

### Decision 1: push 编排迁到 `services/push_dispatcher.py`（模块类）

- **方案 A（采用）**：`push_dispatcher.py` 定义 `PushDispatcher` 类，封装 `_PUSH_CHANNEL` / `_iter_push_rows` / `_run_handle_push` / `_resolve_active_trd_date_safe` / `_dispatch_push` / `_broadcast_trade_cfm` / `_broadcast_generic` / `_log_push_*` 共 8 个成员；transport 持有一个 `PushDispatcher` 实例，`_listen_pushs` 调 `dispatcher.dispatch(pkt, func)`
- **方案 B（拒绝）**：保持模块级函数 + 全局 dispatcher 单例。问题：与 transport 的 `RPClient` 单例模式不一致；测试更难注入 mock
- **方案 C（拒绝）**：搬到 `server/services/push_handlers.py` 子包。问题：REQ-PUSH-010 已规定 push_handlers 子包按事件类型拆分（4 个 handler），再加一个 dispatcher 模糊"handler = 落库函数"的契约
- **理由**：transport 是类（RPClient），保持 dispatcher 也是类可以让 transport 通过构造函数注入（未来如果要做多个 RPClient 实例测试很方便）

### Decision 2: push 行提取独立成 `rpc/parsers_push.py`（不是 parsers_common.py）

- **方案 A（采用）**：新增 `server/rpc/parsers_push.py`，只装 `_iter_push_rows`
- **方案 B（拒绝）**：合进 `parsers_common.py`。问题：`_iter_push_rows` 与 `_iter_rows` 思路不同（不做类型转换），强行合并会让两个 helper 共用一个名字但语义不一致
- **理由**：保持 rpc/parsers_*.py 命名一致性（每个文件一类解析器）

### Decision 3: transport.py 不通过依赖注入 dispatcher，直接 `from services.push_dispatcher import PushDispatcher`

- **方案 A（采用）**：`RPClient.connect()` 内 `self._dispatcher = PushDispatcher(self)`，构造时传 self（方便 dispatcher 拿 push_queue / log 等）
- **方案 B（拒绝）**：`__init__` 接受可选 `dispatcher` 参数，默认 None 时内部 new。问题：增加配置面但本仓库只有 1 个 RPClient 实例，YAGNI
- **理由**：单例架构下没有多 dispatcher 场景；transport 与 dispatcher 是 1:1 绑定，简单构造更清晰

### Decision 4: 测试更新策略 — monkeypatch 目标从 `rpc_client`（facade）改为 facade re-export 的新源模块

- **方案 A（采用）**：保留 `from rpc.client import ...`，monkeypatch 改为 `rpc_client_mod._run_handle_push` 等符号现指向的源模块（即 `services.push_dispatcher`）
- **方案 B（拒绝）**：让测试直接 `from rpc.transport import _run_handle_push` 并 patch `rpc.transport._run_handle_push`。问题：破坏 facade 作为唯一入口的约定；未来再次拆分时测试又得改
- **理由**：facade 是约定入口，测试通过 facade 间接 patch 内部模块符号，定位明确（哪个 helper 来自哪个源模块一目了然）

### Decision 5: `_iter_push_rows` 在 dispatcher 中调用，不在 transport 调用

- **方案 A（采用）**：`_iter_push_rows(pkt)` 移到 dispatcher；transport 把解码后的 pkt 整体传给 `dispatcher.dispatch(pkt, func, msg_type, wire_len)`
- **方案 B（拒绝）**：transport 先调 `_iter_push_rows` 抽成 row 列表再传给 dispatcher。问题：row 提取不是传输职责；且 `_iter_push_rows` 是 MsgPacket 解析，与 parsers_push.py 归属一致
- **理由**：保持职责清晰；transport 不应知道 push 数据长什么样

## Risks / Trade-offs

- [Risk] `RPClient.__init__` 增加 `self._dispatcher = PushDispatcher(self)`，如果 dispatcher 构造抛错会污染 RPClient 实例化 → **Mitigation**: dispatcher 构造只持有引用（self），不调副作用方法，零风险
- [Risk] facade `client.py` re-export 来源调整后，旧测试 `monkeypatch.setattr(rpc_client, "_run_handle_push", ...)` 失效（符号来源变了但 facade 还是 re-export） → **Mitigation**: 验证 facade re-export 后 `rpc.client._run_handle_push is services.push_dispatcher._run_handle_push`；同时更新测试改 patch 源模块
- [Risk] `test_push_listener.py` 里的 `_parse_push_rows` 是 stale 引用（旧名字，本次重构顺手改对） → **Mitigation**: tasks.md 显式列出此修复
- [Risk] 拆分后第一次部署需要走 evctl 重启 + 验证 push 链路端到端 → **Mitigation**: tasks.md 列出重启 + 触发 ord_cfm / trd_cfm 验证步骤；spec 测在沙箱 mock broker 即可
- [Trade-off] 新增 `services/push_dispatcher.py` 让 services 子包从 7 个文件变 8 个 — 可接受，按功能模块拆分的结构（REQ-PUSH-010）继续成立
- [Trade-off] transport.py 持 dispatcher 引用后，`RPClient` 间接依赖 services — 可接受，依赖方向是 transport → services（单向），services 不依赖 transport

## Migration Plan

1. **阶段 1：添加新模块（无破坏）**
   - 新增 `server/rpc/parsers_push.py`（从 transport 搬 `_iter_push_rows`）
   - 新增 `server/services/push_dispatcher.py`（从 transport 搬 8 个 push helper）
   - 两个新模块暂未被任何代码 import（除 transport 自身）
   - 跑现有测试应全绿（transport 内部搬迁，行为不变）

2. **阶段 2：transport.py 切换到新模块**
   - transport.py 删除搬走的 8 个 helper + 4 个 push 类内方法
   - `_listen_pushs` 改为调 `self._dispatcher.dispatch(pkt, func, msg_type, wire_len)`
   - `connect()` 内构造 `self._dispatcher = PushDispatcher(self)`
   - 跑测试：理论上 facade re-export 不变 → client.py 不改前测试应仍绿；client.py 调整 re-export 后再次跑测试

3. **阶段 3：facade re-export 调整**
   - `client.py` 改 5 行 import 来源
   - 跑测试

4. **阶段 4：测试更新**
   - `test_push_listener.py`: `_parse_push_rows` → `_iter_push_rows`；monkeypatch 目标模块调整
   - `test_push_async.py`: monkeypatch 目标模块调整
   - 跑测试

5. **阶段 5：spec 同步**
   - 更新 `openspec/specs/rpc-protocol/spec.md` REQ-RPC-010 / REQ-RPC-011 + 新增 REQ-RPC-012
   - 更新 `openspec/specs/push/spec.md` 新增 REQ-PUSH-020

6. **回滚策略**
   - 每阶段独立 commit，任何阶段失败可 `git revert` 对应 commit
   - 最坏情况：5 个 commit 全部 revert 回到 602 行 transport.py

## Open Questions

- 是否要把 `_PUSH_CHANNEL` 的"未知 func 跳过"逻辑也搬到 dispatcher？目前 transport 路由前已经 check（line 332-334 `if not channel: log.warning(...)`），dispatcher 拿到 func 后再做一遍会重复 — **决议**: dispatcher 接收 func，假定 func 已在 transport 层通过路由表；transport 只做"func → channel"转换并 skip 未知
- `_safe_msg_type` 和 `_count_reply_rows` 是 reply 链路工具，应留在 transport（不是 push）— **决议**: 留在 transport