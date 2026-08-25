# Spec Delta: server-architecture — 删 REQ-ARCH-008

## REMOVED Requirements

### REQ-ARCH-008: Hermes Agent Client + WS Gateway + Confirmation 协议 (2026-08-23, upgrade-agent-to-v1-runs change)

> ❌ 本 REQ 因 `2026-08-25-cleanup-ai-remove` change **整条删除**（Hermes Agent Client + `/ws/agent_channel` WS Gateway + 二次确认状态机）。

理由：用户拍板移除全部 AI 功能。

**删除范围**：
- 后端 `server/ai/agent_spawner.py`（spawn `claude -p` 子进程）
- 后端 `server/ai/mcp_server.py`（HTTP MCP server）
- 后端 `server/ai/tools.py`（7 个 MCP tool handler）
- 后端 `server/ws/endpoint.py::_handle_agent_message` + `agent_channel` 路由分发
- 后端 `server/ws/manager.py::active_connections["agent_channel"]`
- 后端 `server/auth/security.py::HERMES_AGENT_TOKEN` + `server/api/auth.py::/grant`
- 前端 `client/src/api/agent.js::AgentWSClient`（hermes / claudedemo 双协议归一化）

## Notes

- 现有 WS 频道 (`order_update / trade_update / position_update / asset_update / quote_update / system_update / task_progress_update / sync_update`) 保留，去 `agent_channel`。
- `REQ-ARCH-007`（Hermes RPC 客户端）是 `openspec/changes/2026-08-23-ai-strategy-assistant/spec-deltas/server-architecture.md` 的 active draft（未合并），随 change 目录整删而失效。