# 2026-08-23-ai-agent-ws-reuse-channel — AI 助手 WS 复用 /ws/{channel} 路径

## Why

当前 AI 助手 WS 走独立 endpoint `/api/agent/ws`，与现有行情/推送 WS (`/ws/{channel}`) 是两套机制：
- 两套鉴权路径
- 两套心跳（AI 没有）
- 两套 idle timeout（AI 没有）
- 两套消息协议（subscribe vs user_message）
- 前端要连 **两个 WebSocket**

用户拍板：**让 AI 助手 WS 与行情/推送 WS 完全一样处理，复用 `/ws/{channel}` 路径**，AI 作为第 6 个 channel（`agent_channel`）。

> **核心目标：完全一致处理、零新通路、零新机制。**

## What

### 后端 — 把 AI WS 收敛进现有 `/ws/{channel}` endpoint

| 改动 | 文件 |
|---|---|
| `server/ws/endpoint.py` 加 `agent_channel` 分支处理 `user_message` / `confirmation` / `tool_call` / `ping` | 1 file |
| 复用现有 JWT 鉴权 (`_resolve_ws_user`)、`ws_manager.connect/disconnect`、`idle_checker` (10 分钟 idle)、`ping/pong` | 0 新代码 |
| 删除 `server/api/agent.py` 独立 WS endpoint | 1 file 删 |
| `server/main.py` 删 `app.include_router(agent_api.router, ...)` | 1 line 删 |
| `server/services/agent/agent_confirm.py` 保持不变（FastAPI gateway 删后, ConfirmRegistry 由 `/ws/agent_channel` 处理逻辑直接调） | 0 |

### 新消息协议（在 `/ws/agent_channel` 内）

**Vue → FastAPI**：
- `{type: "ping"}` — 复用现有心跳（30s 客户端 ping）
- `{type: "user_message", text: "..."}` — 启动 hermes run
- `{type: "confirmation", pending_key, confirmed}` — 响应高危 tool

**FastAPI → Vue**：
- `{type: "pong", ts}` — 复用现有
- `{type: "ready", session_id}` — agent_channel 特有（连上后发）
- `{type: "text", run_id, content}` — LLM 文本段
- `{type: "tool_call", name, params, run_id}` — tool 调用
- `{type: "tool_result", result, run_id}` — tool 结果
- `{type: "confirmation_required", pending_key, name, params}` — 高危 tool 待确认
- `{type: "agent_complete"}` — agent run 结束
- `{type: "error", message}` — 错误

### 前端

| 改动 | 文件 |
|---|---|
| `client/src/api/agent.js` 改为连 `/ws/agent_channel` | 1 file 改 |
| `client/src/stores/agent.js` WS 路径同步 | 1 file 改 |
| `client/src/components/agent/AgentPanel.vue` 无需改（不变） | 0 |
| `client/vite.config.js` 删 `/api/agent/ws` proxy（不再用） | 1 file 改 |

### 关键不变项

- **端口仍 8000**（FastAPI 单一进程多 WS endpoint）— 仍是**复用端口**
- **JS 单实例 ws_manager**（按 channel 分组）— 现在多了 `agent_channel` 这个分组
- **JWT 鉴权** — 完全复用 `_resolve_ws_user`
- **Idle timeout / ping/pong** — 完全复用
- **WebSocket protocol** — 复用 Starlette WebSocket
- **前端不需要第二个 WS 连接** — 用 `/ws/agent_channel` 单连接即可

## 影响面

| 层 | 改动 |
|---|---|
| 后端 WS endpoint | `server/ws/endpoint.py` 加 agent_channel 分支；删 `server/api/agent.py`；删 main.py 注册 |
| 后端 services | `server/services/agent/hermes_serve_client.py` 改造为同步 WS 推 ws_manager（取代"流式 yield event"） |
| 后端 tests | 删 `server/tests/services/agent/` 改为测试 `server/tests/test_ws_agent_channel.py`（mock hermes serve） |
| 前端 WS 客户端 | `client/src/api/agent.js` 改路径 + 复用 ping/pong |
| 前端 vite proxy | 删 `/api/agent/ws` proxy（保留 `/api` + `/ws`） |
| 文档 | `openspec/specs/server-architecture/spec.md` §REQ-ARCH-008 重写端口复用原则；`openspec/specs/frontend/spec.md` §REQ-FE-537 改 WS 路径 |

## 不做

- ❌ 不新开 WS endpoint
- ❌ 不新开端口（仍 8000）
- ❌ 不新加心跳机制（复用现有）
- ❌ 不新加 idle timeout 机制（复用现有 10 分钟）
- ❌ 不改 ws_manager（直接加 `agent_channel` 分组即可）
- ❌ 不改前端路由或 store 结构
- ❌ 不做 hermes serve 启动管理（用户之前拍板"默认启动即可"）

## 风险

| 风险 | 缓解 |
|---|---|
| agent_channel 与 quote_update 频道并发管理（同一 ws_manager） | ws_manager 已按 channel key 分组，无冲突 |
| ConfirmationRegistry 与 ws_manager 生命周期不匹配 | 改造为在 ws_handler 里直接 await future，不用 ConfirmRegistry 中间层 |
| 删 `/api/agent/ws` 路径后, 已 push 的前端缓存还连旧路径 | vite proxy 不再代理 `/api/agent/ws` → 旧前端连旧路径会 404, 提示用户硬刷新 |
| 单测 21 个 mock 测试要改 | 改写为 mock hermes serve（已存在的 21 测试大部分可复用） |

## 拍板记录

- 复用 `/ws/{channel}` 路径 (用户拍板 2026-08-23)
- AI 作为 `agent_channel` 第 6 个 channel (用户拍板 2026-08-23)
- 共用现有心跳/鉴权/idle/ws_manager 机制 (用户拍板 2026-08-23)
- 不开新端口/新机制 (用户原话"不要新开通路")

## 引用

- `openspec/changes/2026-08-23-ai-agent-panel/` (上版用独立 endpoint 的方案，本 change 是 refactor)
- `server/ws/endpoint.py` (现有 /ws/{channel} 实现 — 直接复用)
- `server/ws/manager.py` (现有 ws_manager — 直接复用)
- `openspec/specs/server-architecture/spec.md` §REQ-ARCH-008 (现行 WS Gateway 契约)
- `openspec/specs/quotes/spec.md` § 行情推送 WS (现有 /ws/quote_update channel)