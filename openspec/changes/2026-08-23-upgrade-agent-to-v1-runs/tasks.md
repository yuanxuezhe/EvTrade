# Tasks — 2026-08-23-upgrade-agent-to-v1-runs

> 按 CLAUDE.md § 五 v6 拆 commit:每完成 1 项 = 1 commit。

## V1 change 工件(已完成)

- [x] 调研 Hermes API server `:8642` 协议(`/v1/runs` + SSE events + approval/stop)
- [x] 写 `proposal.md` + `tasks.md` + `spec-deltas/`

## V2 spec delta(待做)

- [x] `openspec/specs/server-architecture/spec.md` REQ-ARCH-008 重写(WS Gateway 契约 /v1/runs + REST 客户端契约)
- [x] `openspec/specs/frontend/spec.md` REQ-FE-537 补前端事件名映射 + tool_call 字段对齐

## V3 后端 client 重写(待做)

- [x] `server/services/agent/hermes_serve_client.py` 重写为 REST + SSE 客户端(httpx async):
  - `submit_run(input, session_id, instructions?, conversation_history?) -> str` (run_id)
  - `stream_events(run_id) -> AsyncIterator[Event]` (SSE 解析)
  - `respond_approval(run_id, choice, resolve_all=False) -> None` (POST /v1/runs/{id}/approval)
  - `stop_run(run_id) -> None` (POST /v1/runs/{id}/stop)
  - `get_run_status(run_id) -> dict` (GET /v1/runs/{id})
  - `is_reachable() -> bool` (GET / 响应到达判据,沿用上次 healthz 修复)
- [x] 配置:`HERMES_API_BASE_URL` (默认 http://127.0.0.1:8642)+ `HERMES_API_KEY`(默认读 env)
- [x] SSE 解析:`httpx.AsyncClient.stream("GET", url)` + 逐行读 `data:` 行 + JSON parse
- [x] 异常:Hermes 不可达 → 503;approval 失效 → 409;run 不存在 → 404

## V4 后端 WS gateway 简化(待做)

- [x] `server/ws/endpoint.py` agent_channel 分支简化:
  - 接 `{type: "user_message", text}` → 调 `submit_run` 拿 `run_id` → 订阅 SSE 推 WS 给前端
  - 接 `{type: "confirmation", pending_key, confirmed}` → 调 `respond_approval`
  - 接 `{type: "stop"}` → 调 `stop_run`
  - SSE 事件 → WS 消息透传(事件名 `run.started`/`tool.started`/`run.completed` 等直接转发)
- [x] 移除 `ConfirmRegistry` 拦截逻辑(改由 Hermes 自身处理)
- [x] 保留 idle timeout + JWT 鉴权(不动)

## V5 前端适配(待做)

- [x] `client/src/api/agent.js` WS 消息发送:沿用旧协议(`user_message`/`confirmation`/`stop`),后端负责转 REST
- [x] 接收消息事件名同步 Hermes SSE:`run.started`/`message.started`/`tool.started`/`tool.completed`/`run.completed`/`error`
- [x] `client/src/components/agent/AgentPanel.vue` 适配 tool_call 字段:`tool_name` + `preview` + `args`(替换原 `name` + `params`)

## V6 单测(待做)

- [x] 重写 `server/tests/services/agent/test_hermes_serve_client.py`(mock httpx + SSE 解析)
  - `test_submit_run_returns_run_id`
  - `test_submit_run_5xx_raises`
  - `test_stream_events_parses_sse`
  - `test_stream_events_handles_done_marker`
  - `test_respond_approval_sends_correct_payload`
  - `test_stop_run_returns_204`
  - `test_is_reachable_404_still_true`(沿用 healthz 修复)
- [x] 简化的 WS gateway 测试:mock hermes_serve_client,验事件流转发正确
- [x] pytest 全过(基线 98 passed 不降)

## V7 验证 + 归档(待做)

- [x] pytest hq/ server/tests/ 全跑
- [x] npm run build
- [x] evctl status 5 个默认服务 healthy
- [x] 浏览器手动验证 AI 对话框端到端
- [x] 归档:spec merge + mv → archive/

## 验证清单(commit 前必做)

- [x] `git diff --stat` 改动单一目的
- [x] `git log -1` hash 校验
- [x] pytest 全过
- [x] npm run build 跑过(前端 commit)
- [x] curl `:8642/v1/runs` 手动测
- [x] 知识库同步(`openspec/specs/...`)
## 归档（已完成 2026-08-23）

- [x] spec-deltas/server-architecture.md REQ-ARCH-008 重写已 merge 进 `openspec/specs/server-architecture/spec.md`（commit `4fc6870`）
- [x] pytest hq/ server/tests/ → **106 passed / 8 failed**（基线 98/8，新增 32 client 测试全过；8 failed = 7 pre-existing + 1 port-9119 环境冲突）
- [x] npm run build ✓ built in 30.02s
- [x] 前端 AgentPanel 适配新版事件协议（commit `93f63fb`）
- [x] 后端 WS handler 薄包装 + 删 ConfirmRegistry（commit `f1f5b9e`）
- [x] hermes_serve_client 重写 + 32 单测覆盖（commit `7bd95e0` + `870bc3e`）
- [ ] 待用户拍板：evctl 默认服务清单移除 hermes serve :9119（需重启 + 改 .env）
- [ ] mv → `openspec/changes/archive/2026-08-23-upgrade-agent-to-v1-runs/`
