# AI Agent Capability Spec（capability: ai-agent）

**v2026-08-24 立**：EvTrade AI 助手前端右下角浮动按钮 + WS `/ws/agent_channel` → 后端 spawn `claude -p` 子进程 + 本机 HTTP MCP server（claudedemo 模式）。

## 一、架构总览

```
[Vue AgentPanel]
    ↓ WebSocket /ws/agent_channel?token=<user JWT>
[FastAPI: server/ws/endpoint.py]
    ↓ user_message → ClaudeSession.run_turn(text)
[server/ai/agent_spawner.py] — spawn `claude -p` 子进程
    ↓ --mcp-config http://127.0.0.1:{RAND}/mcp
[server/ai/mcp_server.py] — HTTP MCP server (127.0.0.1 随机端口)
    ↓ tools/call
[server/ai/tools.py] — EvTrade 业务调用 (进程内直调 tables/services)
```

**关键决定**：
- 前端 WS 用 Vue 用户 JWT 鉴权（`/api/auth/login` 拿到的普通 token），**不**透传到 claude 子进程
- claude 子进程在 FastAPI 进程内 spawn，**信任边界 = 进程边界**，调 MCP tools 不需再传 user JWT
- claude 自管 auth（OS keychain），spawn 时**不传** `ANTHROPIC_API_KEY` env
- MCP server 仅绑 `127.0.0.1`，**不暴露外网**

## 二、Requirements

### REQ-AI-001: Vue AgentPanel 全局浮动按钮 + WS 直连

- **前端入口**：所有页面右下角 `fixed bottom: 24px; right: 24px;` 一个 56×56 圆形按钮（图标 MagicStick + "🤖 AI" 文字）
- **WS 连接**：`ws://<host>/ws/agent_channel?token=<localStorage['evtrade-token']>`
- **事件协议**：前端 AgentWSClient 发送 `{type: "user_message", text, session_id?, history?}`，接收 `ready / run.started / text / tool_call / tool_result / agent_complete / error / pong`
- **不动现有 UI**：Vue AgentPanel 文件 `client/src/components/agent/AgentPanel.vue` 不修改（按用户拍板）
- 实现位置：`client/src/api/agent.js`

### REQ-AI-002: 后端 WS handler — agent_channel 接入 ClaudeSession

- **端点**：`/ws/agent_channel`（复用现有 `/ws/{channel}` 框架）
- **鉴权**：跟其他 WS channel 一样，token ∈ {用户 JWT, hermesagent}；前端 AgentPanel 用 user JWT
- **WS ready 事件**：连上后**立即**发 `{type: "ready", session_id}`，claude 实际 spawn 推迟到首条 user_message
- **user_message 分发**：调 `ClaudeSession.run_turn(text, history)` 流式推 AgentEvent 给前端
- **错误兜底**：claude CLI 不在 PATH 时返回清晰错误（不是 500）
- 实现位置：`server/ws/endpoint.py::_handle_agent_message`

### REQ-AI-003: ClaudeSession — spawn `claude -p` 子进程

- **spawn 时机**：每 turn（user_message 一次）新 spawn 一个 claude -p 子进程（与 claudedemo 同款）
- **子进程命令**：`claude -p <prompt> --strict-mcp-config --mcp-config <json> --output-format stream-json --verbose --dangerously-skip-permissions --append-system-prompt <md>`
- **mcp-config 注入**：`{"mcpServers": {"evtrade": {"type": "http", "url": "http://127.0.0.1:{mcp_port}/mcp"}}}`
- **stdin**：一次性写完整 prompt（history + current）
- **stdout**：按行解析 `--output-format stream-json` 输出，每行 JSON → AgentEvent
- **stderr**：单独线程 drain，写入 `/tmp/evtrade_claude_stderr.log`（排查 MCP 启动失败）
- **生命周期**：WS 断开 / turn 完成 / spawn 失败 → close 子进程（terminate 5s，kill 兜底）
- 实现位置：`server/ai/agent_spawner.py::ClaudeSession`

### REQ-AI-004: EvTrade MCP HTTP server

- **bind**：`127.0.0.1:RAND`（端口 0 = OS 分配）
- **协议**：streamable-HTTP + JSON-RPC 2.0，单 POST `/mcp`，一请求一连接
- **methods**：
  - `initialize` → `{protocolVersion: "2024-11-05", capabilities: {tools: {}}, serverInfo}`
  - `tools/list` → 7 个 EvTrade 工具 schema
  - `tools/call` → 调 `server.ai.tools.call(name, args)`，返回 `{content: [{type: "text", text}], isError}`
  - `notifications/initialized` → 202 Accepted（无响应）
- **错误码**：JSON-RPC 标准 -32700 (ParseError) / -32601 (MethodNotFound) / -32602 (InvalidParams)
- **session_id**：`Mcp-Session-Id: evtrade-mcp-1`（固定，无状态）
- **lifespan**：`on_startup_ai_mcp_server` 启动，`on_shutdown_ai_mcp_server` 关闭
- 实现位置：`server/ai/mcp_server.py::EvTradeMCPServer`

### REQ-AI-005: MCP tools — EvTrade 业务调用

7 个工具（`server/ai/tools.py`）：

| 工具 | 用途 | 调什么 |
|------|------|--------|
| `list_positions` | 当前持仓 | `Positions.query_all()` |
| `get_asset` | 资金 | `Assets.query_all()` |
| `list_orders` | 委托（可选 trd_date） | `Orders.query_by("trd_date", ...)` |
| `list_trades` | 成交（可选 trd_date） | `Trades.query_by("trd_date", ...)` |
| `list_users` | 用户列表 | `Users.query_all()` |
| `list_stocks` | 股票池（可选 keyword） | `Stocks.query_all()` + 模糊匹配 |
| `ai_analysis` | EvTrade 内置 LLM 分析指定股票 | `server.api.ai_analysis.ai_analysis_for_stock` |

**约束**：
- 进程内直接调 `server.tables.*` / `server.services.*` / `server.api.*`，**不走 HTTP**，**不用 user JWT**（信任边界 = 进程）
- 纯函数，无状态，一次 tool call = 一次 DB query
- 错误抛 `ValueError / KeyError`，mcp_server 转 `isError=True`
- 返回 dict 统一 snake_case 字段名（与 EvTrade REST 一致）

### REQ-AI-006: System Prompt (claudedemo 同款)

- **位置**：`server/ai/system_prompt.md`
- **内容**：7 个工具列表 + 行为规范（必带 `mcp__evtrade__` 前缀 / 一次只调一个 / 回答简洁 / 不确定就问 / 不替用户做高危操作 / 数据无值如实说 / 中文）
- **加载时机**：每次 spawn claude -p 时通过 `--append-system-prompt` 注入（不是 stdin）

## 三、Scenarios

### S-AI-001: 用户登录后点 AI 助手按钮

Given 用户已登录（前端 localStorage 有 `evtrade-token`），点击右下角 AI 按钮
When Vue AgentPanel 调 `ws://.../ws/agent_channel?token=<user JWT>`
Then 后端鉴权通过 → 立即推 `ready` 事件 → 前端可输入 user_message

### S-AI-002: 用户问"我的持仓"

When 前端发 `{type: "user_message", text: "我的持仓"}`
Then 后端 spawn `claude -p` → claude 调 `mcp__evtrade__list_positions` → 推 `tool_call` / `tool_result` / `text` 事件流 → 结束推 `agent_complete`

### S-AI-003: 本机没装 claude CLI

Given EvTrade backend 跑的本机/容器没有 `claude` binary（`which claude` 返回 None）
When 用户点 AI 助手按钮 → 发 user_message
Then 后端立即推 `error: 未在 PATH 中找到 claude CLI...`，前端显示安装指引

### S-AI-004: backend 重启 → MCP server 自动重启

When backend 重启
Then `on_shutdown_ai_mcp_server` 停旧 server → `on_startup_ai_mcp_server` 在新进程内绑新随机端口起新 server → `set_mcp_server(...)` 全局替换

## 四、修改指南

- **新增 MCP tool**：在 `server/ai/tools.py` 加 `tool_xxx` + `schema_xxx` + 注册到 `TOOL_HANDLERS` / `TOOL_SCHEMAS`
- **改 system prompt**：编辑 `server/ai/system_prompt.md`，下次 spawn 自动加载
- **改 claude 命令行参数**：`server/ai/agent_spawner.py::ClaudeSession.start`
- **改 WS 协议**：`server/ws/endpoint.py::_handle_agent_message`（注意前端 AgentWSClient 已有的事件名契约）
- **多租户/权限隔离**：当前所有工具进程内调用，不区分 user role。如需，按 `current_user_id` 参数从 `get_current_user` 透传到 WS handler，再传到 ClaudeSession
- **claude binary 部署约束**：Docker 镜像里 `npm i -g @anthropic-ai/claude-code` + 用户本机 keychain；纯本机开发同理

## 五、依赖

- **依赖**：`claude` CLI（外部进程）；`server.tables` / `server.services` / `server.api.ai_analysis`；FastAPI / starlette WebSocket；Python stdlib `http.server` / `subprocess` / `json`
- **被依赖**：前端 `client/src/components/agent/AgentPanel.vue` + `client/src/api/agent.js`
- **同进程端口**：MCP server 绑 127.0.0.1:RAND；evtrade 主 HTTP 8000；无端口冲突

## 六、影响面与历史

- **删除**：
  - `server/services/agent/hermes_serve_client.py`（429 行）
  - `server/services/agent/__init__.py`（24 行）
  - `server/ws/agent_handler.py`（246 行）
- **新增**：
  - `server/ai/__init__.py`（37 行）
  - `server/ai/tools.py`（300+ 行）
  - `server/ai/mcp_server.py`（200+ 行）
  - `server/ai/agent_spawner.py`（300+ 行）
  - `server/ai/system_prompt.md`
- **修改**：
  - `server/ws/endpoint.py`：`agent_channel` 段改调 `_handle_agent_message`
  - `server/main.py`：`on_startup_ai_mcp_server` + `on_shutdown_ai_mcp_server` lifespan 钩子
- **不修改**：前端 AgentPanel.vue / agent.js；EvTrade 业务 API；其他模块

## 七、参考

- claudedemo 设计参考：`/root/workspcae/codespace/claudedemo/src/{agent,mcp,ui}/*`
- 上线 commit：（待 push 时记录）
- 旧 self-built Hermes 链路 archive 已删：
  - `2026-08-23-ai-agent-panel`
  - `2026-08-23-ai-agent-ws-reuse-channel`
  - `2026-08-23-upgrade-agent-to-v1-runs`