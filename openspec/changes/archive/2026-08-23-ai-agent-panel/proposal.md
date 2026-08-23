# 2026-08-23-ai-agent-panel — 全局 AI 对话助手 (右下角悬浮)

## Why

EvTrade 目前缺一个**全局 AI 助手入口**，用户必须去特定页面（如 ScriptDev）才能用 AI。用户需求：所有页面右下角都应有一个 AI 风格的浮动按钮，点击后在右下角弹出悬浮对话框，可多轮对话、调用 EvTrade 业务 API（查持仓/资金/委托/行情）、执行高危操作（下单/撤单）需二次确认。

> 用户原话：「设计在策略开发页面，右下角悬浮一个 AI 风格的按钮，点击在右下角打开一个悬浮对话框实现 AI 对话」。
>
> **与 `2026-08-23-ai-strategy-assistant` 的关系**：互补 — 后者专做 ScriptDev 单次生成 Python 脚本，本方案做全局多轮对话。两者并存。

## What

### 用户视角

- 所有页面右下角显示一个 `🤖 AI` 浮动按钮（fixed 定位，z-index 最高）
- 点击 → 右下角弹出 480×600 的悬浮对话框（不是 el-drawer，不是右侧抽屉）
- 对话框内：
  - 顶部：标题栏 + 清空按钮
  - 中部：消息列表（用户 / AI 文本 / 工具调用卡片 / thinking spinner）
  - 底部：输入框（textarea + Ctrl+Enter 发送）
- AI 可调用 12 个 EvTrade 业务 tool（查持仓/资金/委托/行情/策略 + 下单/撤单/保存脚本/改权限）
- 高危 tool（下单/撤单/删脚本/改权限）→ 前端弹 Modal 二次确认 → 用户确认后执行
- 多轮对话上下文保持（同一 session 内 LLM 看得到历史）

### 架构

```
┌─────────────────────────┐    WS /api/agent/ws    ┌────────────────────────────┐    Internal HTTP    ┌──────────────────┐
│  Vue 3 (AgentPanel)     │ <─────────────────────>│  FastAPI  (Agent Gateway) │ <─────────────────>│  EvTrade REST    │
│  - 右下角浮动按钮        │     step events + tool │  - WS 端点 /api/agent/ws   │   JWT 透传         │  /api/*          │
│  - 右下角悬浮对话框      │     confirmation 协议   │  - 转发 hermes serve         │                    └──────────────────┘
│  - 工具调用卡片          │                         │  - 拦截 tool call,         │   ┌──────────────────┐
│  - 二次确认 Modal       │                         │    转发 evtrade-mcp         │ <─│  evtrade-mcp     │
└─────────────────────────┘                         │  - JWT 注入 / RBAC 校验     │   │  (本地 MCP server)│
                                                    └────────────────────────────┘   │  暴露 12 个 tool  │
                                                                                      │  调 EvTrade REST  │
                                                                                      └──────────────────�
                                                                                              │
                                                                                              ▼
                                                                                    ┌──────────────────┐
                                                                                    │  hermes serve    │
                                                                                    │  :9119 daemon    │
                                                                                    │  + MiniMax M3    │
                                                                                    └──────────────────┘
```

### 关键设计决策

| 决策 | 选择 | 原因 |
|---|---|---|
| 浮动按钮位置 | **右下角 fixed**（不是 el-drawer rtl） | 用户明确要求 |
| 对话框形态 | **右下角悬浮卡片**（不是右侧抽屉） | 用户明确要求 |
| Hermes tool 暴露 | **MCP server**（不是 `@tool` 装饰器） | Hermes 无装饰器；MCP 是标准协议 |
| 流式输出 | **WS step-complete 事件**（不是 SSE token 流） | Hermes agent loop 按 step 返回，不支持 token 流 |
| JWT 透传 | **MCP tool 内部显式读 JWT**（不是自动透传） | Hermes 不会自动透传；必须在 tool 内实现 |
| 高危操作 | **Modal 二次确认 + 服务端再 RBAC** | 防止 LLM 越权 |

## 涉及 capability

| Cap | 改动 | spec 文件 |
|---|---|---|
| `frontend` | 新增 REQ-FE-537 全局 AgentPanel 浮动按钮 + 悬浮对话框 | `openspec/specs/frontend/spec.md` |
| `server-architecture` | 新增 REQ-ARCH-008 hermes agent client + WS gateway + confirmation 协议 | `openspec/specs/server-architecture/spec.md` |

## 影响面

| 层 | 改动 |
|---|---|
| 前端 | `client/src/components/agent/AgentPanel.vue`（浮动按钮 + 悬浮对话框） + `client/src/components/agent/ConfirmModal.vue`（高危确认） + `client/src/stores/agent.js`（Pinia store） + `client/src/api/agent.js`（WS 客户端） |
| 后端 | `server/api/agent.py`（WS 端点） + `server/services/hermes_agent_client.py`（hermes serve JSON-RPC 客户端） + `server/services/agent_confirm.py`（pending_confirmations 状态机） |
| MCP | `server/mcp/evtrade_mcp_server.py`（独立 MCP server，暴露 12 个 tool） + `server/mcp/tools/*.py`（每个 tool 一个文件） |
| 配置 | `server/.env` 新增 `HERMES_SERVE_WS_URL=ws://127.0.0.1:9119/ws`（可选） + `EVMCP_PORT=8787` |
| Daemon | `hermes serve` 用户手动起（不纳入 evctl 管理 — 与 ai-strategy-assistant 一致） + `evtrade-mcp` FastAPI 启动时 spawn（自动管理） |
| 测试 | `server/tests/test_agent_ws.py`（WS 端点 e2e，mock hermes） + `server/mcp/tests/test_*`（每个 tool 单测） |

## 12 个 Tool 候选清单

| Tool | 高危? | Toolset | 描述 |
|---|---|---|---|
| `list_positions` | ❌ | read-only | 查持仓 |
| `get_asset` | ❌ | read-only | 查资金 |
| `list_orders` | ❌ | read-only | 查委托 |
| `list_trades` | ❌ | read-only | 查成交 |
| `get_quote` | ❌ | read-only | 查行情 |
| `list_strategies` | ❌ | read-only | 查策略 |
| `place_order` | ✅ | trade | 下单 |
| `cancel_order` | ✅ | trade | 撤单 |
| `save_strategy_script` | ❌ | write | 保存策略脚本（草稿） |
| `delete_strategy_script` | ✅ | write | 删除脚本 |
| `set_user_role` | ✅ | admin | 改用户角色 |
| `init_trading_day` | ✅ | admin | 系统日初 |

## 不做

- ❌ 不取代 `2026-08-23-ai-strategy-assistant`（并存）
- ❌ 不做 `@tool` 装饰器（Hermes 无此 API）
- ❌ 不做 SSE token 流（Hermes agent loop 不支持）
- ❌ 不让 Hermes 自动透传 JWT（tool 内部实现）
- ❌ 不纳入 hermes serve 到 evctl 管理（~~已推翻 2026-08-23~~ → 用户拍板纳入 evctl 默认服务，见 `openspec/changes/2026-08-23-hermes-serve-evctl/`）
- ❌ 不做对话历史持久化（v1 仅内存 session；v2 再加 DB）
- ❌ 不做多用户并发同一 session（每 session 单 user）

## 风险

| 风险 | 缓解 |
|---|---|
| LLM prompt injection 越权 | (a) tool 参数从 JWT 强制注入 user_id (b) RBAC 服务端再校验 (c) 高危 tool 二次确认 |
| Hermes serve 未起 | FastAPI WS 连接时 health check → 503 + 提示 |
| MCP server 挂了 | FastAPI 启动时 spawn + health check；挂了 FastAPI 返 503 |
| WS 长连接断 | Vue 客户端自动重连（指数退避）+ 恢复未完成消息 |
| 二次确认超时 | 60s 默认超时 → 返回 "user rejected (timeout)" 给 LLM |
| Hermes 不是 token 流式 | 已设计成"thinking spinner + step_complete 文本段"两态 UX |
| MiniMax key 过期 | 复用现有 MINIMAX_CN_API_KEY 路径 |

## 拍板记录

- 入口位置：右下角浮动按钮（用户拍板 2026-08-23）
- 对话框形态：右下角悬浮对话框（非 el-drawer；用户拍板 2026-08-23）
- 不影响 ai-strategy-assistant（用户拍板 2026-08-23）
- Hermes tool 暴露：MCP server（订正用户原方案）
- 流式：WS step events（订正用户原方案）
- JWT 透传：tool 内部实现（订正用户原方案）

## 引用

- `openspec/changes/2026-08-23-ai-strategy-assistant/`（单次生成脚本助手，与本方案并存）
- `知识库/全局规范.md` § 二、修改流程 § 三、改动范围铁律
- `~/.hermes/skills/autonomous-ai-agents/hermes-agent/SKILL.md`（Hermes 真实 API 文档）
