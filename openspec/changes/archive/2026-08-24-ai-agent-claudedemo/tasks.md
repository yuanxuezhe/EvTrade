# 2026-08-24-ai-agent-claudedemo — Tasks

> 上线 commit：`9422e3f` + `a14a558` + `bb0d6ea` + 前端归一化层（commit 提交时补）

## V1: 后端核心模块（feat(ai)）

- [x] `server/ai/__init__.py` — 包描述，~37 行
- [x] `server/ai/tools.py` — 7 个 MCP tool (list_positions / get_asset / list_orders / list_trades / list_users / list_stocks / ai_analysis)
- [x] `server/ai/mcp_server.py` — HTTP MCP server (127.0.0.1:RAND, JSON-RPC over streamable-HTTP)
- [x] `server/ai/agent_spawner.py` — spawn `claude -p` 子进程 + stream-json 解析
- [x] `server/ai/system_prompt.md` — tool 列表 + 行为规范
- [x] MCP server 起/停/测试 — bind 127.0.0.1:RAND / tools/list / tools/call / notification 全过
- [x] 7 个 tool 调通 — list_positions / get_asset / list_stocks / list_users 实际查 DB OK

## V2: WS endpoint 接入 + main.py lifespan（refactor）

- [x] `server/ws/endpoint.py` — 删 agent_handler import + send_agent_ready 替换 + agent_channel 改调 `_handle_agent_message`
- [x] `server/ws/endpoint.py` — 新增 `_handle_agent_message` 函数（user_message 分发 + 流式推 AgentEvent）
- [x] `server/main.py` — `_ai_mcp_server = None` 全局单例 + `on_startup_ai_mcp_server` / `on_shutdown_ai_mcp_server` 钩子
- [x] 删 `server/services/agent/*`（455 行）
- [x] 删 `server/ws/agent_handler.py`（246 行）
- [x] 删 `server/tests/services/agent/*`（477 行）
- [x] backend 重启 health 200 + MCP server 起好（日志确认）

## V3: 文档同步（docs(openspec) + skill + proposal）

- [x] `openspec/specs/ai-agent/spec.md` — REQ-AI-001~006 + S-AI-001~004
- [x] `openspec/AGENTS.md` — 删 3 个旧 archive，加新 `2026-08-24-ai-agent-claudedemo` 链接
- [x] `openspec/changes/archive/2026-08-24-ai-agent-claudedemo/proposal.md` — 完整 why + what + 影响面
- [x] `~/.hermes/skills/evtrade/evtrade-ai-claudedemo/SKILL.md` — AI 助手第一步必加载
- [x] `CLAUDE.md` §四首条改写：AI 助手走 `/ws/agent_channel` + claude CLI 部署约束

## V4: 前端协议归一化（client/src/api/agent.js）

- [x] `_dispatch` switch case 改造：text / tool_call / tool_result / agent_complete → emit `onText / onToolCall / onToolCompleted / onRunCompleted`
- [x] 新增 `_normalizeEvent(msg)` 函数：claudedemo 字段名 → Hermes 字段名映射
- [x] 字段映射：`text→content` / `name→tool` + `input→args` + `preview=JSON.stringify(input)` / `content→result`
- [x] `npm run build` 通过（19.58s）

## V5: 测试

- [x] `server/tests/test_ws_agent_channel.py` 重写：6 test pass（ready 推送 + user_message 分发 + claude 缺失兜底 + 空 text 兜底 + MCP server 缺失兜底）
- [x] pytest `hq/ server/tests/test_ws_agent_channel.py` — 6/6 passed
- [x] pytest `hq/ server/tests/` — 16 failed + 7 errors 全为历史基线（push / rpc / place_async / script_new / script_strategy_compile），与本 change 无关

## V6: 验证清单

- [x] 后端 health 200 ✅
- [x] `[INIT] AI MCP server started on http://127.0.0.1:PORT/mcp` ✅
- [x] MCP server 7 个 tool list/call OK ✅
- [x] 前端 npm run build OK ✅
- [x] pytest 不破基线 ✅
- [x] git push origin master OK（3 commit）✅

## 已知遗留

- [ ] **claude binary 部署约束**：用户需在 EvTrade backend 同机/容器装 `npm i -g @anthropic-ai/claude-code`（用户待办）
- [ ] pytest 16 failed + 7 errors 是历史基线，不在本 change 范围
- [ ] starlette 0.27 + httpx 0.28 TestClient 不兼容（旧 AgentPanel integration test 被替换为 inspect 源码测试）