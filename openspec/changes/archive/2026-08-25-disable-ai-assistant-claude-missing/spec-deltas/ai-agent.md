# Spec Delta — ai-agent (2026-08-25-disable-ai-assistant-claude-missing)

## REQ-AI-007: AI 助手能力探测 endpoint

- **端点**：`GET /api/ai/status`（**无需鉴权**，公开）
- **响应**：
  - claude CLI 在 PATH：`{"available": true}`
  - 缺失：`{"available": false, "reason": "未在 PATH 中找到 claude CLI..."}`
- **作用**：前端启动时探测，决定 AI 助手浮动按钮是否启用
- **实现**：`server/main.py` 新增路由，调 `server.ai.is_claude_available()`
- **不依赖**：`shutil.which("claude")` 实时查（不 cache，避免 PATH 变化后失同步）

## REQ-AI-008: WS handler claude-missing 错误兜底

- **触发**：`_handle_agent_message` 收到 `user_message` 时 `_which_claude() is None`
- **旧行为**：只推 `{type: "error", message: "..."}` 然后 return → 前端 `isThinking` 卡死
- **新行为**：error 事件后**追加推** `{type: "agent_complete", success: false, error: "claude_cli_missing"}` → 前端 `onRunCompleted` 收到 → `isThinking=false`
- **前端契约**：必须容忍"error 事件后可能仍有 agent_complete 事件"（不是 bug，是设计上保证兜底）
- **实现**：`server/ws/endpoint.py::_handle_agent_message` 错误分支

## 修改 S-AI-003 (本机没装 claude CLI 场景)

原场景描述：
> Given EvTrade backend 跑的本机/容器没有 `claude` binary（`which claude` 返回 None）
> When 用户点 AI 助手按钮 → 发 user_message
> Then 后端立即推 `error: 未在 PATH 中找到 claude CLI...`，前端显示安装指引

**新增**：
> 前端 `useAgentStore.openPanel()` 调用前先 `await fetchAgentStatus()`：
> - 若 `available=false`：按钮 disabled，hover tooltip 显示 `reason`；点不开
> - 若 `available=true`：正常连 WS
> - 若 fetch 本身失败（FastAPI 没起）：默认 `available=true` 保持原行为（最坏回退到当前路径，WS 错误兜底）

## 影响面
- `server/main.py` 加 1 个 endpoint（~10 行）
- `server/ai/agent_spawner.py` 加 1 个 public 函数（~5 行）
- `server/ws/endpoint.py::_handle_agent_message` 错误分支加 1 行 send_json（~3 行）
- `client/src/api/agent.js` 加 `fetchAgentStatus()`（~10 行）
- `client/src/stores/agent.js` 加 2 个 state + openPanel 改写（~15 行）
- `client/src/components/agent/AgentPanel.vue` 浮动按钮 disabled + tooltip（~5 行）

## 测试
- `server/tests/api/test_ai_status.py`：新文件
- `server/tests/ws/test_agent_channel_degraded.py`：新文件