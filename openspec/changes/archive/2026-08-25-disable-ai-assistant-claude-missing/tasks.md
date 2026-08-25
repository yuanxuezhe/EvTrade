# Tasks — 2026-08-25-disable-ai-assistant-claude-missing

> 按 CLAUDE.md § 五 v6 拆 commit：每完成 1 项 = 1 commit。

## C0 调研 + change (已完成)

- [x] 排查 claude 缺失链路影响面：server/ws/endpoint.py::_handle_agent_message + 前端 store/AgentPanel
- [x] 写 proposal.md + tasks.md + spec-deltas/

## C1 后端：AI 状态探测 endpoint

- [ ] `server/ai/agent_spawner.py` 加 `is_claude_available() -> bool` (公开函数, 包 `_which_claude()`)
- [ ] `server/ai/__init__.py` 暴露 `is_claude_available`
- [ ] `server/main.py` 加 `GET /api/ai/status` 端点（无需鉴权, 返 `{available, reason?}`）
- [ ] 验证: `curl http://localhost:8000/api/ai/status` 返 `{available: false, reason: "..."}`
- [ ] commit: `feat(ai): add /api/ai/status endpoint for client capability probe`

## C2 后端：WS handler 错误兜底（推 agent_complete 双事件）

- [ ] `server/ws/endpoint.py::_handle_agent_message` 当 `_which_claude() is None` 时,
      除 `error` 事件外**追加推** `{type: "agent_complete", success: false, error: "claude_cli_missing"}`
- [ ] 验证: pytest `server/tests/ws/test_agent_channel_degraded.py::test_claude_missing_pushes_complete_event`
- [ ] commit: `fix(ai): ws handler emits agent_complete on claude-missing so spinner clears`

## C3 后端：单测 (api + ws)

- [ ] `server/tests/api/test_ai_status.py`: 测 `available=false` (当前环境) + `available=true` (mock `_which_claude` 返路径)
- [ ] `server/tests/ws/test_agent_channel_degraded.py`: 测 WS handler 推 `error` + `agent_complete` 双事件
- [ ] commit: `test(ai): cover ai-status endpoint + ws degraded path`

## C4 前端：agent store 加能力探测 + 禁用状态

- [ ] `client/src/api/agent.js` 加 `fetchAgentStatus()` 调 `/api/ai/status` (无 JWT)
- [ ] `client/src/stores/agent.js` 加 `agentAvailable` + `agentUnavailableReason` state
      `openPanel()` 前先 await fetch, 不可用直接 set lastError + 不连 WS
- [ ] commit: `feat(frontend): agent store probes /api/ai/status before opening panel`

## C5 前端：AgentPanel 浮动按钮灰显 + 提示

- [ ] `client/src/components/agent/AgentPanel.vue`:
      浮动按钮 `:disabled="!store.agentAvailable"` + 灰显 + tooltip 展示 reason
      面板打开时 header 加降级提示条
- [ ] commit: `feat(frontend): disable AI fab when claude CLI unavailable`

## C6 spec merge + 归档

- [ ] `openspec/specs/ai-agent/spec.md` 合并 spec-deltas/ 内容
- [ ] `openspec/specs/frontend/spec.md` 合并 REQ-FE-539 (AI 助手能力探测 + 降级 UI)
- [ ] 跑 `pytest hq/ server/tests/` 全过 (基线 64 passed 不能掉)
- [ ] `mv openspec/changes/2026-08-25-disable-ai-assistant-claude-missing openspec/changes/archive/`

## 备注

- 调研 + proposal 已先于 C1 完成 (C0)
- C1/C2/C3 = 后端 3 commit, C4/C5 = 前端 2 commit = 总 5 commit
- 不自动 push —— 等用户拍板