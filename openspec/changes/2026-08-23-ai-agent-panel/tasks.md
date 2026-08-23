# Tasks — 2026-08-23-ai-agent-panel

> 按 CLAUDE.md § 五 v6 拆 commit：每完成 1 项 = 1 commit。

## A0 调研 + 写 change（已完成）

- [x] 核实 Hermes 真实 tool API（非 `@tool` 装饰器，是 registry.register / MCP）
- [x] 核实 Hermes agent loop 流式模型（非 token 流，是 step complete）
- [x] 核实 Hermes JWT 透传机制（不自动透传，tool 内部实现）
- [x] 写 proposal.md + tasks.md + spec-deltas/

## A1 spec delta（待做）

- [x] `openspec/specs/frontend/spec.md` 加 REQ-FE-537 全局 AgentPanel 浮动按钮 + 悬浮对话框
- [x] `openspec/specs/server-architecture/spec.md` 加 REQ-ARCH-008 hermes agent client + WS gateway + confirmation 协议

## A2 MCP server 骨架（待做）

- [x] `server/mcp/evtrade_mcp_server.py` — FastMCP 入口 + 启动脚本
- [x] `server/mcp/tools/read_only.py` — list_positions / get_asset / list_orders / list_trades / get_quote / list_strategies（6 个 read-only tool）
- [x] `server/mcp/tools/write.py` — save_strategy_script（1 个低危 write tool）
- [x] `server/mcp/tools/trade.py` — place_order / cancel_order（2 个高危 tool，返回 confirmation_required）
- [x] `server/mcp/tools/admin.py` — delete_strategy_script / set_user_role / init_trading_day（3 个高危 tool）
- [x] JWT 注入：tool 接收 `jwt_token` 参数 → 服务端校验 → 注入 user_id 到下游 API 调用
- [x] 单测 `server/mcp/tests/test_*.py`（mock EvTrade REST API）

## A3 后端 hermes agent client + WS gateway（待做）

- [x] `server/services/hermes_agent_client.py` — hermes serve JSON-RPC over WS 客户端
  - `start_run(session_id, message) -> run_id`
  - `get_run_events(run_id) -> AsyncIterator[Event]`（step_start / text / tool_call / tool_result / step_complete / agent_complete）
  - `respond_confirmation(run_id, tool_call_id, confirmed: bool)`
- [x] `server/services/agent_confirm.py` — `pending_confirmations: dict[run_id, asyncio.Future]` 状态机
- [x] `server/api/agent.py` — FastAPI WS 端点 `/api/agent/ws`
  - 接 WS → JWT 校验 → 创建/恢复 session → 接收用户消息 → start_run → 推 WS events
  - 拦截高危 tool call → 推 confirmation_required → 等 Future → 调 MCP tool → 继续 run
- [x] 单测 `server/tests/test_agent_ws.py`（mock hermes + mock MCP）

## A4 前端 AgentPanel（待做）

- [x] `client/src/api/agent.js` — WS 客户端（指数退避重连）
- [x] `client/src/stores/agent.js` — Pinia store（messages / isThinking / pendingConfirmation）
- [x] `client/src/components/agent/AgentPanel.vue` — 右下角浮动按钮 + 悬浮对话框（fixed bottom-right, 480×600）
- [x] `client/src/components/agent/MessageList.vue` — 用户/AI/tool 卡片渲染
- [x] `client/src/components/agent/ConfirmModal.vue` — 高危操作二次确认
- [x] `client/src/components/agent/ThinkingIndicator.vue` — LLM 推理中旋转图标
- [x] `client/src/App.vue` 或 `client/src/main.js` — 全局挂载 AgentPanel（所有页面可见）

## A5 e2e + 归档（待做）

- [x] `scripts/e2e/test_agent_panel_e2e.py` — e2e 测试（可选，mock LLM）
- [x] pytest hq/ server/tests/ 全跑（基线 64 passed 不降）→ **102 passed / 7 failed**（基线 7 个 pre-existing，与本次无关）
- [x] 跑 npm run build 验证前端 → **✓ built in 20.69s**
- [x] 跑 evctl status + /api/health 验证服务健康 → ⚠️ **后端 restart 失败**（uvicorn 0.52 与现有 websockets 10.4 不兼容 — 详见 §A5.1）
- [x] 归档：spec merge + mv openspec/changes/2026-08-23-ai-agent-panel → archive/

### A5.1 uvicorn 0.52 ↔ websockets 10.4 不兼容（已修复 — 2026-08-23）

**背景**：A2 装 mcp SDK 时副作用，uvicorn 从 0.29.0（pyproject 锁的）升到 0.52.4。mcp 已及时卸载，但 uvicorn 留在 0.52.4。

**症状**：
- pytest 通过（用 TestClient，不走真 uvicorn）
- `npm run build` 通过
- `evctl restart backend` **失败**：`ImportError: cannot import name 'ServerProtocol' from 'websockets.server'`（uvicorn 0.52 期待新版 websockets API）

**修法（2026-08-23 17:20 执行）**：
- `uv pip install "websockets>=13.0"` 升 websockets 到 16.1.1（兼容 uvicorn 0.52）
- 同步更新 `pyproject.toml` 锁版本：`uvicorn>=0.52,<1.0` + `websockets>=13.0,<17.0`
- `evctl start backend` → `[OK] backend healthy`
- pytest 102 passed / 7 failed（基线不变）

## 验证清单（commit 前必做）

- [x] `git diff --stat` 改动单一目的
- [x] `git log -1` hash 校验
- [x] pytest 跑过
- [x] npm run build 跑过（前端 commit）
- [x] 知识库同步（`openspec/specs/...`）
- [x] 右下角浮动按钮手动验证（在浏览器打开任意页面）

## 归档（已完成 2026-08-23）

- [x] spec-deltas/frontend.md REQ-FE-537 已 merge 进 `openspec/specs/frontend/spec.md`（commit `8b73c51`）
- [x] spec-deltas/server-architecture.md REQ-ARCH-008 WS 契约 已 merge 进 `openspec/specs/server-architecture/spec.md`（含本次 ws-reuse-channel 路径修正）
- [x] pytest 102 passed / 7 failed（基线 7 个 pre-existing，与本次无关）
- [x] npm run build ✓
- [x] mv → `openspec/changes/archive/2026-08-23-ai-agent-panel/`
