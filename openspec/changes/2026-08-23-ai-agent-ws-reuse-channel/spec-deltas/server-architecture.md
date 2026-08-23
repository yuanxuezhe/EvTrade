# Spec Delta — server-architecture (AI WS 复用 /ws/{channel} 路径)

## REQ-ARCH-008 重写 — AI WS 复用 /ws/agent_channel（不新开通路）

> 详见 change `openspec/changes/2026-08-23-ai-agent-ws-reuse-channel/`（refactor 自上版独立 endpoint 方案）。

### Purpose

把 AI 助手 WS 收敛进现有 `/ws/{channel}` endpoint（行情/推送用的同一套），AI 作为第 6 个 channel `agent_channel`。**完全复用现有鉴权/心跳/idle/ws_manager 机制**，**0 新端口/0 新 endpoint/0 新机制**。

### WS Gateway 契约（重写）

- **端点**：`WS /ws/agent_channel`（与 `/ws/quote_update` / `/ws/order_update` / `/ws/trade_update` / `/ws/position_update` / `/ws/asset_update` **共用同一 endpoint handler**，仅 channel 名不同）
- **复用**：
  - JWT 鉴权：`server.ws.endpoint._resolve_ws_user` (支持 JWT + hermesagent token)
  - 连接管理：`server.ws.manager.ws_manager`（按 channel key 分组连接）
  - Idle timeout：`server.ws.endpoint.WS_IDLE_TIMEOUT` (10 分钟无消息 close 4001)
  - 单向心跳：客户端 30s 主动 ping → 服务端 pong（**重置 last_recv**）
  - HTTP session 续期：ping 触发 `session_touch(token)`
- **WS handler 分支**（在现有 `if msg_type == "ping"` / `== "subscribe"` 后加）：
  ```python
  if channel == "agent_channel":
      await _handle_agent_channel_message(ws, parsed)
      continue
  ```

### agent_channel 业务消息

**Vue → FastAPI**（客户端发）：
- `{type: "ping"}` — 复用现有 ping（30s 心跳）
- `{type: "user_message", text: "..."}` — 启动 hermes run
- `{type: "confirmation", pending_key, confirmed}` — 响应高危 tool 二次确认

**FastAPI → Vue**（服务端推）：
- `{type: "pong", ts}` — 复用现有
- `{type: "ready", session_id}` — 连上后立即发
- `{type: "text", run_id, content}` — LLM 文本段（非流式 token）
- `{type: "tool_call", name, params, run_id}` — LLM 决定调 tool
- `{type: "tool_result", result, run_id}` — tool 返回结果
- `{type: "confirmation_required", pending_key, name, params}` — 高危 tool 等用户确认
- `{type: "agent_complete", run_id}` — agent run 结束
- `{type: "error", message, run_id}` — 错误

### 高危 tool 拦截

- WS handler 收到 `tool_call` event（从 hermes 流式事件转）+ `is_high_risk(tool_name)`
- 注册 `ConfirmRegistry` pending（`pending_key = "{run_id}:{tool_call_id}"`）
- 推 `confirmation_required` 给 Vue
- 用户响应 → 调 `_execute_tool` 真正执行 → 推 `tool_result` → 调 `hermes.respond_confirmation`

### 端口复用原则（不变）

- 与 `/api/quote/*` HTTP、所有 `/ws/{channel}` WS 共用 FastAPI 8000 端口
- **0 新端口/0 新 endpoint**

### Scenario: agent_channel 与 quote_update 共存

- **GIVEN** FastAPI 服务监听 8000 端口，注册 `/ws/{channel}` endpoint
- **WHEN** 用户连 `ws://host:8000/ws/quote_update?token=...`（行情订阅）
- **AND** 用户连 `ws://host:8000/ws/agent_channel?token=...`（AI 对话）
- **THEN** 两个 WS 共存，分别由 `ws_manager.subscribe_index` 与 `agent_sessions` 跟踪
- **AND** 任一连接 idle 超时都触发独立 close 4001
- **AND** 互不干扰

### Scenario: agent_channel 高危 tool 二次确认

- **GIVEN** 用户连 `/ws/agent_channel` 已 ready
- **WHEN** 用户发 `{type: "user_message", text: "帮我下单 100 股 600000.SH"}`
- **THEN** FastAPI 调 hermes run；hermes 流式返回 tool_call `place_order`
- **WHEN** FastAPI 检测 `is_high_risk("place_order") == True`
- **THEN** 推 `{type: "confirmation_required", pending_key: "r-1:tc-1", name: "place_order", params: {...}}`
- **WHEN** 用户在 60s 内发 `{type: "confirmation", pending_key: "r-1:tc-1", confirmed: true}`
- **THEN** FastAPI 调 MCP tool 真执行下单；推 `{type: "tool_result", result: {...}}`
- **AND** hermes 整合结果返回自然语言
- **WHEN** 60s 无响应
- **THEN** ConfirmRegistry 自动 cancel；推 `{type: "error", message: "confirmation timeout"}`

### Out of Scope (v1)

- AI 对话历史持久化（v1 仅内存 session）
- 跨页面 session 同步
- 对话式多轮历史页（独立 feature）