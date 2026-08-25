# 2026-08-25-disable-ai-assistant-claude-missing — Claude CLI 缺失时优雅降级

## 为什么改

2026-08-25 上午按用户拍板删除了系统上的 Claude Code CLI（npm 包、native binary、`/root/.claude/` 配置目录全清，详见 commit history）。**EvTrade AI 助手后端链路依赖 `claude -p` 子进程**（`server/ai/agent_spawner.py::ClaudeSession.start`），链路已成死路：

1. **WS `/ws/agent_channel` 能连上**（`server/ws/endpoint.py:118-121` 立刻发 `ready` 事件，claude 实际 spawn 推迟到首条 `user_message`）
2. 用户在浏览器点 AI 助手浮动按钮 → 前端 `store.openPanel()` → `_connect()` → `AgentWSClient` 收到 `ready` → 按钮变绿"已连接"
3. 用户发第一条 user_message → 后端 `_handle_agent_message` → `_which_claude() is None` → 推 `{type: "error", message: "未在 PATH 中找到 claude CLI..."}` → return
4. **前端 `onRunStarted` 已把 `isThinking=true`，但 `onError` 只 set `lastError`，前端 spinner 卡死 + 用户看不到 "已禁用" 状态**

spec `S-AI-003` 已预言"本机没装 claude CLI"场景，但实现只做了"error 事件告诉前端"，没做**前端能力探测 + UI 降级**。

## 目标

把"claude 缺失"从"用户点开才知道坏了"改成"前端加载时就禁用，按钮变灰 + 提示"，并让 WS 错误事件真正兜底（不再卡 spinner）。

## 范围

### 改
- `server/ai/agent_spawner.py`：加 `_claude_available() -> bool` 公开函数（已有 `_which_claude()` 是 private，加个 public）
- `server/ws/endpoint.py::_handle_agent_message`：claude 缺失时除 error 外**追加推 `{type: "agent_complete", success: false, error: "claude_cli_missing"}`**，让前端 `onRunCompleted` 能清 `isThinking`
- `server/main.py`：在 `_AUTH` 之外加 `GET /api/ai/status` 端点（无需 JWT，公开；返回 `{available: bool, reason?: str}`），给前端启动时探测用
- `client/src/api/agent.js`：新增 `fetchAgentStatus()` 调 `/api/ai/status`
- `client/src/stores/agent.js`：加 `agentAvailable: ref(bool, true)` + `agentUnavailableReason: ref('')`；`openPanel()` 之前先 fetch 状态，若不可用直接 `set lastError` 不连 WS
- `client/src/components/agent/AgentPanel.vue`：浮动按钮当 `!store.agentAvailable` 时 `:disabled="true"` + 灰显 + tooltip 展示 reason；面板打开时 header 也展示降级提示

### 增
- `server/tests/api/test_ai_status.py`：单测 `/api/ai/status` 在 claude 缺失时返 `{available: false, reason: "..."}`，存在时返 `{available: true}`
- `server/tests/ws/test_agent_channel_degraded.py`：单测 WS handler 在 `_which_claude() is None` 时推 `error` + `agent_complete` 双事件

### 不改
- `server/ai/system_prompt.md`、`server/ai/tools.py`、`server/ai/mcp_server.py`：MCP server 跟 claude 缺失无关，独立运转
- 前端 `AgentPanel.vue` 整体布局 / 消息渲染：仅加按钮 disabled + 提示
- EvTrade 业务 API、其他 WS channel：完全不动

## 验收

1. 后端跑起来（_which_claude() 返 None 现状）→ `curl http://localhost:8000/api/ai/status` 返 `{"available": false, "reason": "未在 PATH 中找到 claude CLI..."}`
2. 浏览器访问 EvTrade → 右下角 AI 按钮灰显 + hover tooltip "AI 助手暂不可用：Claude CLI 未安装"
3. 强点按钮（绕过 disabled 测兜底）→ 后端 WS 推 `error` + `agent_complete` 双事件 → 前端 spinner 不会卡死
4. 重装 claude CLI（`npm i -g @anthropic-ai/claude-code-linux-x64@<ver> && node install.cjs`）→ `/api/ai/status` 返 `{available: true}` → 按钮恢复
5. pytest `server/tests/api/test_ai_status.py` + `server/tests/ws/test_agent_channel_degraded.py` 全过

## 风险

- **误报**：`/api/ai/status` 是进程内查 `shutil.which("claude")`，如果在某次启动后动态 PATH 变化（例如临时 source 了一个虚拟环境），状态会过期 → 接受，前端用户重连 WS 即可重新探测
- **多 worker**：uvicorn 单 worker 进程内查 OK；多 worker 时每个 worker 各自查（保持简单，不做 cache）
- **前端 fetch 时机**：`_connect()` 之前先 `await fetchAgentStatus()`；若 fetch 自身失败（FastAPI 没起）→ 降级为默认 `available=true`（保持原行为，最坏情况回到今天）

## 不做

- **不重写 AI 助手链路**（不替换 claude -p 模型、不引入其他 LLM 后端）—— 用户明确说"删 Claude Code CLI"，没说"换成 X"。当前范围只是"删后让 UI 别炸"
- **不删 server/ai/ 目录**——保留所有代码，等用户后续决定换哪个 AI 引擎时复用
- **不删 ClaudeSession 类**——仅在 start 失败路径里给清晰错误即可
- **不动 spec.md 的架构总览**——本次纯降级 / 错误处理加固，不动 AI 助手架构本身