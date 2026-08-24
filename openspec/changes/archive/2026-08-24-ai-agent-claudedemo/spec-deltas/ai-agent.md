# Spec Deltas: ai-agent (新增 capability)

## 新增 capability `ai-agent`

将 `server/ai/*` + `/ws/agent_channel` 后端调度 + `client/src/components/agent/AgentPanel.vue` 前端入口 整合为 capability `ai-agent`。

具体 REQ 见 `openspec/specs/ai-agent/spec.md`：

- **REQ-AI-001**: Vue AgentPanel 全局浮动按钮 + WS 直连
- **REQ-AI-002**: 后端 WS handler — agent_channel 接入 ClaudeSession
- **REQ-AI-003**: ClaudeSession — spawn `claude -p` 子进程（per-turn）
- **REQ-AI-004**: EvTrade MCP HTTP server (127.0.0.1:RAND, streamable-HTTP)
- **REQ-AI-005**: MCP tools — EvTrade 业务调用（7 个 tool）
- **REQ-AI-006**: System Prompt (claudedemo 同款)

## 不变更其他 capability

- `auth/spec.md` REQ-AUTH-011 / REQ-AUTH-013 保留（grant 端点 + WS token=hermesagent 兜底仍生效）
- `frontend/spec.md` REQ-FE-537 保留（AgentPanel 入口仍生效，UI 不变）
- 其他 capability 不受影响

## 影响 cap 索引

`openspec/AGENTS.md` § 8 个 capability 表格加一行 `ai-agent`：
- 范围：AI 助手后端调度 + 前端 AgentPanel
- 关键文件：`server/ai/{__init__,tools,mcp_server,agent_spawner}.py` + `server/ws/endpoint.py::_handle_agent_message` + `client/src/components/agent/AgentPanel.vue`