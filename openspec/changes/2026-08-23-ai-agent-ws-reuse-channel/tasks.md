# Tasks — 2026-08-23-ai-agent-ws-reuse-channel

> 按 CLAUDE.md § 五 v6 拆 commit：每完成 1 项 = 1 commit。

## B1 change 工件（已完成）

- [x] 写 `openspec/changes/2026-08-23-ai-agent-ws-reuse-channel/proposal.md`
- [x] 写 `tasks.md`
- [x] 写 spec-deltas/server-architecture.md (重写 REQ-ARCH-008 §WS Gateway 契约)

## B2 后端：endpoint.py 加 agent_channel 分支（待做）

- [ ] `server/ws/endpoint.py`: 加 `if channel == "agent_channel":` 分支处理 user_message / confirmation / 其他消息
- [ ] 复用 `_resolve_ws_user` / `ws_manager.connect` / `idle_checker` — 0 新机制
- [ ] WS message 分发: `{type: "user_message"}` → 启动 hermes run + 推 ws_manager.send_to(agent_channel, ws, event)
- [ ] `{type: "confirmation"}` → 解析 ConfirmationRegistry pending_key + 继续 hermes run
- [ ] 任何消息自动 last_recv 更新（已复用）

## B3 hermes_serve_client 改造（待做）

- [ ] 把 `subscribe_events(run_id) -> AsyncIterator[HermesEvent]` 改为 `stream_to_ws(run_id, ws_send_func) -> None`（直接推 ws 不再 yield）
- [ ] 加 `is_reachable_for_channel(channel)` 健康检查方法
- [ ] 删 `start_run` 返回 run_id 改直接传 ws_send_func
- [ ] 测试：原 14 个 hermes_serve_client 测试要更新（流式 → 回调）

## B4 ConfirmRegistry 适配（待做）

- [ ] 移除 ConfirmRegistry.respond 异步特性（改为 ws_channel 直接调）
- [ ] 或保持 ConfirmRegistry 但加 `pending_by_key: dict[pending_key, Future]` 让 ws_handler 能 await
- [ ] 单测：原 7 个 ConfirmRegistry 测试保留（接口不变）

## B5 删除独立 /api/agent/ws endpoint（待做）

- [ ] `git rm server/api/agent.py`
- [ ] `server/main.py`: 删 `app.include_router(agent_api.router, ...)` 5 行
- [ ] 删 `server/tests/services/agent/test_hermes_serve_client.py` (B3 改造后已无意义,重写)
- [ ] 删 `server/tests/services/agent/test_agent_confirm.py` (或保留,接口不变)

## B6 前端路径同步（待做）

- [ ] `client/src/api/agent.js`: WS_PATH 改 `/ws/agent_channel`
- [ ] `client/src/stores/agent.js`: 无需改（用 agent.js 默认路径）
- [ ] `client/vite.config.js`: 删 `/api/agent/ws` proxy（保留 `/api` + `/ws`）
- [ ] `cd client && npm run build` 验证

## B7 测试 + 归档（待做）

- [ ] pytest hq/ server/tests/ 全跑（基线 64 passed 不降 + MCP 17 + agent 改造后新增）
- [ ] 跑 evctl restart backend + frontend 验证服务
- [ ] 归档：spec merge + mv openspec/changes/2026-08-23-ai-agent-ws-reuse-channel → archive/

## 验证清单（commit 前必做）

- [ ] `git diff --stat` 改动单一目的
- [ ] `git log -1` hash 校验
- [ ] pytest 全过
- [ ] npm run build 跑过（前端 commit）
- [ ] /ws/agent_channel 手动测试（连上后发 user_message 应收到 ready 事件）
- [ ] 知识库同步（`openspec/specs/...`）