# Cleanup: 移除 AI 助手 + AI 分析页 + 相关整条链路代码

> 2026-08-25 用户拍板：「目前系统里面的 AI 都有问题，帮我先清理干净，后面我再重新构思方案。」

## Why

EvTrade 当前 AI 链路在生产环境行为不稳定（claude CLI 依赖、协议归一化兼容、MCP HTTP server 复杂度、agent_channel WS 死锁等历史 bug），用户决定**先整条清空**，等需求明确后再重构。当前 change 是一次性删除 AI 链路全部代码，不保留任何 `agent` / `hermes` / `claude` / `ai_` / `AgentPanel` / `AiAnalysis` 业务实体。

## What

### 删除范围（前端）

- `client/src/components/agent/AgentPanel.vue`（全局浮动按钮 + 悬浮对话框）
- `client/src/stores/agent.js`（Pinia store）
- `client/src/api/agent.js`（WS 客户端 + `/api/ai/status` 探测）
- `client/src/api/ai_analysis.js`（分析 REST 客户端）
- `client/src/views/AiAnalysis.vue`（AI 分析视图）
- `client/src/components/agent/` 空目录
- 引用方：
  - `client/src/App.vue`（删 `<AgentPanel />` + import）
  - `client/src/router/index.js`（删 `/ai-analysis` 路由 + 懒加载）
  - `client/src/components/Sidebar.vue`（删 "AI 分析" 菜单项；`DataAnalysis` 图标保留，策略下单用）
  - `client/vite.config.js`（删过期 `/api/agent/ws` 注释）

### 删除范围（后端）

- `server/ai/` 整个目录（claudedemo MCP 链路）：
  - `__init__.py` / `agent_spawner.py`（spawn `claude -p` 子进程）/ `mcp_server.py`（HTTP MCP server）/ `tools.py`（7 个 tool handler）/ `system_prompt.md`
- `server/api/ai_analysis.py`（invest-analyst PoC REST endpoint）
- `server/mcp/` 整个目录（旧自建 MCP 链路，main.py 未 import，仅 self-tests 用 → 顺手清 dead code）
- `server/api/auth.py` 的 `/api/auth/grant` endpoint（hermesagent 授信专用）
- `server/auth/security.py` 的 `HERMES_AGENT_TOKEN` 常量
- `server/ws/endpoint.py`：
  - 删 `_resolve_ws_user` 的 `token == HERMES_AGENT_TOKEN` 分支
  - 删 `agent_channel` ready 推送（line 112-121）
  - 删主循环 `if channel == "agent_channel"` 分发（line 240-245）
  - 删 `_handle_agent_message` 整函数（line 259-350）
  - 删 `from server.ai.*` import
- `server/ws/manager.py`：删 `active_connections["agent_channel"]` key
- `server/main.py`：
  - 删 `from server.api import ai_analysis ...` / `from server.ai.agent_spawner ...`
  - 删 `_ai_mcp_server` 全局变量
  - 删 `on_startup_ai_mcp_server` / `on_shutdown_ai_mcp_server` 钩子
  - 删 `app.include_router(ai_analysis_api.router, ...)`
  - 删 `@app.get("/api/ai/status")` 公开探测
- `server/.env.dev` / `.env.prod` / `.env.example`：删 `EVTRADE_ALLOW_GRANT_TOKEN` 行（如有）

### 删除范围（脚本）

- `scripts/evctl.py`：
  - 删 docstring 中 `|hermes` / hermes 说明段
  - 删 `_hermes_cmd()` + `_hermes_preflight()` 函数
  - 删 `SERVICES['hermes']` 条目
  - `OPTIONAL_SERVICES` 改回 `['broker']`（无外部 CLI 类服务）
  - 改 preflight 描述 "如 hermes CLI 存在性" 段落
- `scripts/init_strategy_exec_env.py`：删 `request_grant_token()` 函数 + `--grant` flag 段（hermesagent grant 专用）

### 删除范围（测试）

- `server/tests/test_ai_status.py`
- `server/tests/test_ws_agent_channel.py`
- `server/tests/auth/test_ws_hermes_token.py`
- `server/tests/test_evctl_hermes.py`

### 删除范围（OpenSpec specs + KB）

- 删 `openspec/specs/ai-agent/spec.md` + 目录（10 个 REQ 整篇失效）
- `openspec/specs/frontend/spec.md` 删 REQ-FE-537（AgentPanel）/ REQ-FE-539（AI fab 降级）
- `openspec/specs/server-architecture/spec.md` 删 REQ-ARCH-008（Hermes WS Gateway）
- `openspec/specs/dev-process-control/spec.md` 删 `### Requirement: evctl 管理 hermes serve daemon` 段
- 删 `openspec/changes/2026-08-23-ai-strategy-assistant/` 整目录（active draft change 取消，C1-C5 全废）
- `openspec/AGENTS.md` 删活跃 change 表中 6 条 AI 归档行 + 段首注释
- 7 个 KB 文件删 AI 章节（启停脚本 / 数据与环境工具 / 认证与JWT / WS端点 / 路由与权限 / 架构概览 / 测试体系）

## 不变项

- 业务 JWT 鉴权完整保留（仅删 `HERMES_AGENT_TOKEN` 捷径分支）
- WS 频道保留：`order_update / trade_update / position_update / asset_update / quote_update / system_update / task_progress_update / sync_update`
- `CLAUDE.md` 不动（是给 AI 协作工具看的全局规则，非实体功能）
- 历史归档 `openspec/changes/archive/2026-08-**-ai-*/` 不动（git 历史留痕）
- `pyproject.toml` 不动（无 AI Python dep）
- `.github/workflows/ci.yml` 不动（无 AI step）
- `server/tables/` 不动（无 AI 表）

## Impact

- 用户：右下角浮动按钮消失；`/ai-analysis` 路由 404；菜单少一项
- WS：8 个频道 → 7 个（去 `agent_channel`）
- Auth：常规 JWT 不变；少 1 条 hardcoded admin 凭证捷径（安全性 +1）
- 后端 main.py 启动钩子数：8 → 6
- 测试：删 4 个 AI 测试文件后，pytest 通过基线应仍 ≥ 历史基线
- 资源：删 ~1700 行死代码 + 17 个文件 + 4 个目录

## v6 Commit 拆分

按层拆 10 个 commit（单 commit 单目的，便于 revert）：

| # | commit | 涉及层 |
|---|---|---|
| 1 | `docs(openspec): 建 cleanup-ai-remove change + spec delta` | OpenSpec |
| 2 | `refactor(frontend): 删 AgentPanel + AiAnalysis + 链路 6 处引用` | 前端 |
| 3 | `refactor(server-auth): 删 HERMES_AGENT_TOKEN + /grant + WS 直连免鉴权` | 后端 auth |
| 4 | `refactor(server-ai): 删 server/ai/* + ai_analysis API + WS agent_channel handler` | 后端 AI |
| 5 | `refactor(server-mcp): 删 dead code server/mcp/` | 后端 dead code |
| 6 | `test(server): 删 4 个 AI 测试文件` | 后端测试 |
| 7 | `chore(scripts): evctl 去 hermes + init_strategy_exec_env 去 hermesagent grant` | 脚本 |
| 8 | `docs(知识库): 同步删除 8 个 KB 文件的 AI 章节` | KB |
| 9 | `docs(openspec): AGENTS.md 活跃 change 表清理` | OpenSpec index |
| 10 | `docs(openspec): 归档 cleanup-ai-remove + 更新 AGENTS.md 活跃表` | 归档 |

## KB 同步铁律 (§ 十一)

KB 同步在 commit 8 一次性完成（`docs(知识库)`），与 spec 删除分开。详见 commit 8 列出的 7 个文件。