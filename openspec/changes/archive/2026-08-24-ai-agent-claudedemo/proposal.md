# 2026-08-24-ai-agent-claudedemo — EvTrade AI 助手架构重做

## 为什么改

EvTrade 后端 AI 助手自 2026-08-23 起基于 Hermes API server `/v1/runs` REST + SSE 链路（`server/services/agent/hermes_serve_client.py` + `server/ws/agent_handler.py` + `server/ws/endpoint.py` agent_channel 处理），存在以下问题：

1. **过度工程**：Vue AgentPanel → WS → endpoint → agent_handler → hermes_serve_client → Hermes SSE → MCP tool → EvTrade REST，5+ 段链路
2. **重复造轮子**：自己实现了 JSON-RPC over WS、self-built SSE event protocol、ConfirmRegistry 高危拦截，claudedemo（`/root/workspcae/codespace/claudedemo`）用 `claude -p --mcp-config http://...` 2 段链路就解决同样问题
3. **后端进程 vs 客户端 LLM 混在一起**：Hermes API server 是常驻 daemon，claude CLI 是 stateless per-turn process，混用导致状态管理复杂

## 目标

按 claudedemo 模式重写 AI 助手后端调度：

- 前端 AgentPanel UI / Vue 组件**不动**（按用户拍板）
- 前端 `client/src/api/agent.js` 加 claudedemo 协议 → Hermes 协议归一化层（不动 store / AgentPanel.vue）
- 后端 spawn `claude -p` 子进程（**无状态，每 turn 一次新进程**），通过 `--mcp-config http://127.0.0.1:RAND/mcp` 注入本机 HTTP MCP server
- MCP server 绑 127.0.0.1 随机端口，仅 loopback 可达，进程内 FastAPI 启动 lifespan 钩子托管
- claude 自管 auth（OS keychain），spawn 时**不传** ANTHROPIC_API_KEY
- MCP tools 进程内直接调 `server.tables.*` / `server.services.*`，**不走 HTTP、不用 user JWT**（信任边界 = 进程边界）

## 范围

### 删
- `server/services/agent/__init__.py`（24 行）
- `server/services/agent/hermes_serve_client.py`（429 行）
- `server/ws/agent_handler.py`（246 行）
- `server/tests/services/agent/__init__.py`（3 行）
- `server/tests/services/agent/test_hermes_serve_client.py`（474 行）
- `openspec/changes/archive/2026-08-23-ai-agent-panel/`（5 文件）
- `openspec/changes/archive/2026-08-23-ai-agent-ws-reuse-channel/`（4 文件）
- `openspec/changes/archive/2026-08-23-upgrade-agent-to-v1-runs/`（3 文件）
- 7 个前置 commit（revert）：grant role / dynamic admin id / evtrade_grant.py / evtrade_ai.sh / e2e grant 改造 / REQ-AUTH-014 / doc(ai-helper)

### 增
- `server/ai/__init__.py`（37 行）
- `server/ai/tools.py`（~290 行，7 个 MCP tool + schema）
- `server/ai/mcp_server.py`（~190 行，HTTP MCP server + JSON-RPC dispatch）
- `server/ai/agent_spawner.py`（~300 行，claude -p 子进程 + stream-json 解析）
- `server/ai/system_prompt.md`（~50 行）
- `openspec/specs/ai-agent/spec.md`（REQ-AI-001~006 + S-AI-001~004）
- `~/.hermes/skills/evtrade/evtrade-ai-claudedemo/SKILL.md`（~250 行）

### 改
- `server/ws/endpoint.py`：删 agent_channel → 改调 `agent_spawner.ClaudeSession`；`send_agent_ready` 替换为内嵌 ready 推送
- `server/main.py`：lifespan 加 `on_startup_ai_mcp_server` / `on_shutdown_ai_mcp_server`
- `server/tests/test_ws_agent_channel.py`：重写测 claudedemo 新协议（6 test pass）
- `CLAUDE.md` §四首条：删 grant helper 路径，改 AI 助手走 `/ws/agent_channel`（claudedemo 模式）
- `openspec/AGENTS.md`：3 个旧 archive 替换为新 `2026-08-24-ai-agent-claudedemo`
- `client/src/api/agent.js`：`_dispatch` 加 claudedemo → Hermes 归一化层（`_normalizeEvent`）

### 不动
- `client/src/components/agent/AgentPanel.vue`（前端 UI 按用户拍板）
- `client/src/stores/agent.js`（store 期望的 Hermes 字段由归一化层提供）
- `client/src/api/index.js`、`client/src/router/`、`client/src/views/*`（其他前端文件）
- EvTrade 业务 API（positions / asset / orders / trades / users 等）
- 后端 server/auth/*、server/infra/*、server/api/*（非 AI 模块）
- 数据库 schema（v130+）

## 关键设计决策

| 决策 | 理由 |
|------|------|
| FastAPI 进程内 spawn claude -p | 同进程内 spawn = 进程级信任边界，不用 user JWT |
| MCP server 仅绑 127.0.0.1:RAND | OS 分配端口避免冲突；loopback = 不暴露外网 |
| claude 自管 auth（不传 ANTHROPIC_API_KEY env）| 各终端本地 keychain 独立，避免全局 key 泄露 |
| per-turn 新 spawn claude | claudedemo 同款；claude -p stateless，无需进程复用 |
| spawn 前立即发 ready（懒 spawn）| 防 WS 前后端互相等待死锁（旧 self-built 实测 bug） |
| 归一化层在 client/src/api/agent.js | 前端 store / Vue 不动；只 WS client 一处做兼容 |

## 部署约束（新硬要求）

**`claude` CLI 必须装在 EvTrade backend 跑的本机/容器内**，否则 AI 助手不可用：
- 安装：`npm i -g @anthropic-ai/claude-code`
- 验证：`which claude` 返回非 None
- 后端 WS handler 在 claude 不在 PATH 时返清晰错误（不是 500）

## 引用

- spec：`openspec/specs/ai-agent/spec.md`（REQ-AI-001~006）
- 知识库：暂无专用文件（前端 AgentPanel.vue / 后端 server/ai/* 自带 docstring）
- skill：`~/.hermes/skills/evtrade/evtrade-ai-claudedemo/SKILL.md`（AI 助手进 EvTrade 第一步必加载）
- 设计参考：`/root/workspcae/codespace/claudedemo/src/{agent,mcp,ui}/*`
- 上线 commit：bb0d6ea（docs）+ a14a558（refactor）+ 9422e3f（feat）+ 前端归一化层（commit 提交时补）

## Pitfall Bank

| Pitfall | Symptom | Fix |
|---------|---------|-----|
| backend 日志没 `[INIT] AI MCP server started` | MCP server 启动失败 | 看后端 traceback；常见端口端口冲突 |
| 调 MCP tools 返 `internal: ...` | tool 内部抛异常 | 看后端 stack trace；多是 `server.tables.*` 字段名不匹配 |
| `claude -p` 不退出 | 子进程 hang | agent_spawner 已加 5s wait + kill 兜底 |
| claude binary 缺失 | `error: 未在 PATH 中找到 claude CLI...` | 安装 `npm i -g @anthropic-ai/claude-code` |
| 前端 AgentPanel 看不到消息 | 事件名不匹配 | 验证 `client/src/api/agent.js:_normalizeEvent` 字段映射 |
| backend 重启后前端 WS 断 | session cache 进程内 | 前端应自动重连（AgentWSClient 已有指数退避） |