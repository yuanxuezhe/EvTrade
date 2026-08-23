# 2026-08-23-ai-strategy-assistant — ScriptDev AI 策略助手

## Why

用户在 ScriptDev 页面编写策略脚本时，目前只能手写。需求：用户用自然语言描述策略 → AI 自动生成可用的 Python 策略代码 → 注入到 ScriptDev 编辑器 → 用户可在编辑器中继续迭代修改。

> 用户原话：「在策略开发页面增加一个 AI 策略助手，给他描述策略后，他能根据我的需求生成策略」。

## What

### 用户视角

- ScriptDev 页面顶部「AI 助手」按钮 → 点击展开右侧抽屉（drawer）
- 抽屉内：自然语言输入框 + 「让 Hermes 生成」按钮 + 生成历史列表
- AI 返回的策略代码 → 通过 el-message-confirm 确认 → 直接注入到 ScriptDev 编辑器（替换 `form.code`）
- 用户可继续在编辑器中手动修改/保存

### 技术路径

```
ScriptDev (前端)
  ↓ POST /api/ai-strategy { description, current_code? }
FastAPI server/api/ai_strategy.py (新增)
  ↓ POST /v1/chat (JSON-RPC, hermes serve 默认 127.0.0.1:9119)
hermes serve daemon (默认启动, 不纳入 evctl 管理)
  ↓ delegate_task 或 chat 调用
MiniMax M3.0 (复用 .env MINIMAX_CN_API_KEY)
  ↓ 返回策略代码 (python 代码块)
FastAPI 校验 → 仅返回代码块 (剥离 markdown prose)
  ↓ 注入 ScriptDev 编辑器
```

### 沙箱边界（关键约束）

- **AI 只能返回代码字符串**，**不能**让 LLM 直接写 EvTrade 任何文件
- 后端解析 LLM 输出 → 仅提取 ```python ... ``` 代码块 → 其余丢弃
- LLM 调用走 hermes 沙箱（hermes 默认 `worktree` 隔离），prompt 注入策略模板 + 当前 form.code（可选）

## 涉及 capability

| Cap | 改动 | spec 文件 |
|---|---|---|
| `strategy` | 新增 REQ-STRAT-022 AI 助手契约 | `openspec/specs/strategy/spec.md` |
| `frontend` | 新增 REQ-FE-536 ScriptDev AI 抽屉 | `openspec/specs/frontend/spec.md` |
| `server-architecture` | 新增 REQ-ARCH-007 hermes RPC 客户端 + 沙箱 | `openspec/specs/server-architecture/spec.md` |

## 影响面

| 层 | 改动 |
|---|---|
| 前端 | `client/src/views/ScriptDev.vue`（加抽屉 + 按钮） + `client/src/api/ai_strategy.js`（新增 axios 客户端） |
| 后端 | `server/api/ai_strategy.py`（新增路由） + `server/services/hermes_client.py`（hermes serve JSON-RPC 封装） + `server/api/__init__.py`（注册 router） |
| 配置 | `server/.env` 新增 `HERMES_SERVE_URL=http://127.0.0.1:9119`（可选，默认值已硬编码） |
| Daemon | `hermes serve` 用户手动起（不纳入 evctl 管理 — 用户拍板） |
| 测试 | `server/tests/test_ai_strategy.py`（mock hermes serve 测代码提取 + 错误处理） |

## 不做

- ❌ 不写 hermes-httpd 包装（hermes serve 已是 daemon）
- ❌ 不让 LLM 直接写 EvTrade 文件（沙箱化）
- ❌ 不纳入 evctl 4 服务管理（用户拍板：默认启动即可）
- ❌ 不做会话记忆（每次独立请求，简化 MVP）
- ❌ 不做对话式多轮（v1 只单次生成，v2 再迭代）
- ❌ 不做 token 流式（v1 等 LLM 返回完整结果）

## 风险

| 风险 | 缓解 |
|---|---|
| LLM 输出含 prose 噪声 | 后端正则提取 ```python ... ``` 代码块 |
| LLM 生成代码可执行但语义错 | 不做静态分析（v1），由用户在编辑器 review 后保存 |
| hermes serve 未起 | 后端 try/except → 返 503 + 提示「请起 hermes serve」 |
| MiniMax key 过期/未配 | 复用现有 MINIMAX_CN_API_KEY .env 路径（已就绪） |
| ScriptDev 只读模式 | AI 抽屉在只读时不渲染（与 `isReadonly` 同生命周期） |

## 拍板记录

- 入口位置：ScriptDev 顶部「AI 助手」按钮 + 右侧抽屉（用户拍板 2026-08-23）
- 实现方式：FastAPI 调 hermes serve daemon（用户拍板 2026-08-23）
- Hermes 启动：默认启动即可，不纳入 evctl 管理（用户拍板 2026-08-23）
- 调用方式：单次生成，无对话（用户拍板 2026-08-23）

## 引用

- `知识库/全局规范.md` § 二、修改流程 § 三、改动范围铁律
- `openspec/specs/strategy/spec.md` REQ-STRAT-014~017 现行脚本策略契约
- `openspec/specs/dev-process-control/spec.md` § commit 规范 v6
