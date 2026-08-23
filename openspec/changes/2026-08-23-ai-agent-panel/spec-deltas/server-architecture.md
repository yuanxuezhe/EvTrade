# Spec Delta — server-architecture (Hermes Agent Client + WS Gateway)

## REQ-ARCH-008: Hermes Agent Client + WS Gateway + Confirmation 协议 (2026-08-23, ai-agent-panel change)

### Purpose

EvTrade 后端需要作为 **WebSocket Gateway** 桥接 Vue 前端和外部 Hermes Agent daemon，支持多轮对话、Function Calling（通过 MCP server）、高危操作二次确认协议。

### 客户端契约

- **文件**：
  - `server/services/hermes_agent_client.py`（hermes serve JSON-RPC over WS 客户端）
  - `server/services/agent_confirm.py`（pending_confirmations 状态机）
- **接口**（hermes_agent_client.py）：
  - `start_run(session_id: str, user_message: str) -> str`（返回 run_id）
  - `get_run_events(run_id: str) -> AsyncIterator[Event]`
  - `respond_confirmation(run_id: str, tool_call_id: str, confirmed: bool) -> None`
  - `is_reachable() -> bool`
- **协议**：JSON-RPC over WebSocket（与 hermes serve 兼容）
- **配置**：`HERMES_SERVE_WS_URL` 环境变量（默认 `ws://127.0.0.1:9119/ws`）

### WS Gateway 契约

- **文件**：`server/api/agent.py`
- **端点**：`WS /api/agent/ws`
- **协议**（双向 JSON 消息）：
  - Vue → FastAPI：`{type: "user_message", text: "..."}` / `{type: "confirmation", run_id, tool_call_id, confirmed}`
  - FastAPI → Vue：`{type: "step_start"}` / `{type: "text", content}` / `{type: "tool_call", name, params}` / `{type: "tool_result", result}` / `{type: "confirmation_required", run_id, tool_call_id, name, params}` / `{type: "agent_complete"}` / `{type: "error", message}`
- **JWT 校验**：WS 连接握手时校验 query param `?token=<jwt>` → 注入 user_id 到 session
- **Session 管理**：每 (user_id, ws_connection) 一个 session_id，session_id = uuid4

### MCP Server 契约

- **文件**：`server/mcp/evtrade_mcp_server.py`（FastMCP 入口）
- **端口**：`EVMCP_PORT=8787`（独立 daemon）
- **Tool 列表**：12 个（见 proposal.md）
- **JWT 注入**：每个 tool 必须接收 `jwt_token: str` 参数 → 服务端校验 → 用 user_id 调下游 EvTrade REST API
- **高危 tool**：`place_order` / `cancel_order` / `delete_strategy_script` / `set_user_role` / `init_trading_day` — 不直接执行，返回 `{"status": "confirmation_required"}`，由 FastAPI gateway 拦截并推给前端确认
- **启动方式**：FastAPI 启动时 spawn 子进程（用 `subprocess.Popen`），FastAPI 退出时 kill

### 二次确认协议

- FastAPI 维护 `pending_confirmations: dict[run_id, asyncio.Future[bool]]`
- 拦截 MCP tool call（白名单）→ 不调 MCP → 推 WS `confirmation_required` → 等 Future（60s 超时）
- 用户在 Vue Modal 确认 → FastAPI 解析 Future → 调 MCP tool（这次真执行）→ 继续 hermes run
- 超时 / 用户拒绝 → Future cancel + 返回 `{"status": "user_rejected"}` 给 hermes → LLM 整合自然语言响应

### 沙箱边界

- LLM **不得**指定 user_id（所有 tool 的 user_id 从 JWT 强制注入）
- LLM **不得**看到其他用户的资源（tool 返回结果只含当前 user 的数据）
- LLM **不得**写 EvTrade 任意文件（tool 只能调预定义 REST API）
- 高危 tool **必须**经前端二次确认

### 测试

- `server/tests/test_agent_ws.py`：
  - `test_ws_jwt_required`（无 token → 401）
  - `test_ws_user_message_runs_agent`（mock hermes）
  - `test_ws_high_risk_tool_triggers_confirmation`（mock MCP + mock Vue 确认）
  - `test_ws_confirmation_timeout_rejects`（60s 不响应 → user_rejected）
- `server/mcp/tests/test_*`：每个 tool 独立单测（mock httpx）

### Refs

- `openspec/changes/2026-08-23-ai-agent-panel/proposal.md`
- `openspec/specs/server-architecture/spec.md` REQ-ARCH-001 ~ REQ-ARCH-007 现有契约
- `~/.hermes/skills/autonomous-ai-agents/hermes-agent/SKILL.md`
