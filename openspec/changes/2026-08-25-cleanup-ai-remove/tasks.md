# Tasks: cleanup-ai-remove (2026-08-25)

> 每个 task = 1 个 commit（v6 单 commit 单目的）。

## Commit 拆解

- [ ] **commit 1**: `docs(openspec): 建 cleanup-ai-remove change + spec delta`
  - 新建 `openspec/changes/2026-08-25-cleanup-ai-remove/{proposal.md, tasks.md, spec-deltas/*}`
  - `openspec/specs/frontend/spec.md`：删 REQ-FE-537（2428-2497）、REQ-FE-539（2521-2559）
  - `openspec/specs/server-architecture/spec.md`：删 REQ-ARCH-008（467-?）
  - `openspec/specs/dev-process-control/spec.md`：删 `### Requirement: evctl 管理 hermes serve daemon` 段（231-253）
  - 删 `openspec/specs/ai-agent/` 整目录
  - 删 `openspec/changes/2026-08-23-ai-strategy-assistant/` 整目录

- [ ] **commit 2**: `refactor(frontend): 删 AgentPanel + AiAnalysis + 链路 6 处引用`
  - 删 `client/src/components/agent/AgentPanel.vue` + 目录
  - 删 `client/src/stores/agent.js` / `client/src/api/agent.js` / `client/src/api/ai_analysis.js` / `client/src/views/AiAnalysis.vue`
  - `client/src/App.vue`：删 `<AgentPanel />` + import
  - `client/src/router/index.js`：删 `/ai-analysis` 路由 + 懒加载
  - `client/src/components/Sidebar.vue`：删菜单项
  - `client/vite.config.js`：删过期注释

- [ ] **commit 3**: `refactor(server-auth): 删 HERMES_AGENT_TOKEN + /grant + WS 直连免鉴权`
  - `server/auth/security.py`：删 HERMES_AGENT_TOKEN 常量
  - `server/api/auth.py`：删 /grant endpoint + EVTRADE_ALLOW_GRANT_TOKEN env 处理
  - `server/ws/endpoint.py`：删 `_resolve_ws_user` 的 hermesagent 分支 + import + 注释
  - `server/.env.dev` / .env.prod / .env.example：删 EVTRADE_ALLOW_GRANT_TOKEN

- [ ] **commit 4**: `refactor(server-ai): 删 server/ai/* + ai_analysis API + WS agent_channel handler`
  - `rm -rf server/ai/`
  - `rm server/api/ai_analysis.py`
  - `server/main.py`：删 ai_analysis / agent_spawner / mcp_server import + 启动钩子 + /api/ai router + /api/ai/status
  - `server/ws/endpoint.py`：删 agent_channel 分发 + `_handle_agent_message` + import
  - `server/ws/manager.py`：删 `active_connections["agent_channel"]`

- [ ] **commit 5**: `refactor(server-mcp): 删 dead code server/mcp/`
  - `rm -rf server/mcp/`

- [ ] **commit 6**: `test(server): 删 4 个 AI 测试文件`
  - `rm server/tests/test_ai_status.py`
  - `rm server/tests/test_ws_agent_channel.py`
  - `rm server/tests/auth/test_ws_hermes_token.py`
  - `rm server/tests/test_evctl_hermes.py`

- [ ] **commit 7**: `chore(scripts): evctl 去 hermes + init_strategy_exec_env 去 hermesagent grant`
  - `scripts/evctl.py`：删 _hermes_cmd / _hermes_preflight / SERVICES[hermes] / OPTIONAL hermes / 注释
  - `scripts/init_strategy_exec_env.py`：删 request_grant_token + --grant flag

- [ ] **commit 8**: `docs(知识库): 同步删除 8 个 KB 文件的 AI 章节`
  - `知识库/脚本工具/启停脚本.md` (6 处)
  - `知识库/脚本工具/数据与环境工具.md` (1 处)
  - `知识库/后端服务/用户鉴权/认证与JWT.md` (2 处)
  - `知识库/后端服务/WebSocket推送/WS端点.md` (7 处)
  - `知识库/前端/路由与权限.md` (1 处)
  - `知识库/前端/架构概览.md` (2 处)
  - `知识库/开发流程/测试体系.md` (1 处)

- [ ] **commit 9**: `docs(openspec): AGENTS.md 活跃 change 表清理`
  - `openspec/AGENTS.md`：删 6 条 AI 归档行 + 段首注释

- [ ] **commit 10**: `docs(openspec): 归档 cleanup-ai-remove + 更新 AGENTS.md 活跃表`
  - `mv openspec/changes/2026-08-25-cleanup-ai-remove openspec/changes/archive/`
  - `openspec/AGENTS.md`：加新归档条目

## 验证 (v6 完成自查)

- [ ] `grep -ri "AgentPanel|useAgentStore|aiAnalysisApi|HERMES_AGENT|agent_channel" client/src server/ scripts/` → 业务零命中
- [ ] `uv run python scripts/evctl.py restart` → 4 服务 green
- [ ] `curl /api/health` → 200
- [ ] `curl http://127.0.0.1:50998/` → 200
- [ ] `cd client && npm run build` → 不报 import 错
- [ ] `pytest server/tests/` → 通过剩余用例（≥ 71 passed / 7 failed 历史基线）
- [ ] `git log -10 --oneline` → 10 个独立 commit，主题对应 tasks.md 编号