# Spec Delta — frontend (全局 AgentPanel)

## REQ-FE-537: 全局 AI 对话助手浮动按钮 (2026-08-23, ai-agent-panel change)

### Purpose

在所有页面右下角提供全局 AI 对话助手入口，用户可多轮对话、调用 EvTrade 业务 API、执行高危操作（下单/撤单）需二次确认。

### UI 契约

- **入口**：所有页面右下角 `fixed bottom: 24px; right: 24px;` 一个 56×56 圆形按钮（`data-el="agent-fab"`）
- **图标**：🤖 AI 文字 + MagicStick 图标
- **点击** → 右下角弹出 480×600 悬浮对话框（`fixed bottom: 96px; right: 24px;`，z-index 9999）
- **对话框结构**：
  - 顶部 header：标题"🤖 AI 助手" + "清空"按钮
  - 中部消息列表（MessageList 子组件）
  - 底部 footer：textarea 输入框 + 发送按钮
- **二次确认**：高危 tool 调用时弹 ElMessageBox.confirm（覆盖层，非消息流内）

### 消息类型

| 类型 | 渲染 |
|---|---|
| `user` | 蓝色气泡，右对齐，纯文本 |
| `assistant_text` | 灰色气泡，左对齐，`markdown-it` 渲染 |
| `tool_call` | 工具卡片（图标 + 名称 + status tag + params + result） |
| `thinking` | 旋转 spinner + "AI 思考中..." |

### 状态机

| 状态 | 触发 | 副作用 |
|---|---|---|
| `closed` | 默认 | 仅浮动按钮可见 |
| `open-empty` | 点按钮 | 显示空对话框 |
| `sending` | 用户发消息 | 输入框 disable + 按钮 loading |
| `thinking` | LLM 推理 | thinking spinner |
| `tool-executing` | tool 在跑 | 工具卡片 status='executing' |
| `confirming` | 高危 tool | 弹 ElMessageBox.confirm |
| `streaming` | LLM 返回文本段 | 累积到 assistant_text 气泡 |
| `complete` | agent run 结束 | 显示 AI 最终回复 |

### 不做（v1）

- 对话历史持久化（v1 仅内存 session）
- 多用户并发同一 session
- 跨页面 session 同步（v1 每个 tab 独立 session）
- 拖拽/最小化悬浮窗

### Refs

- `openspec/changes/2026-08-23-ai-agent-panel/proposal.md`
- `openspec/changes/2026-08-23-ai-strategy-assistant/`（并存，单次生成脚本助手）
- `openspec/specs/frontend/spec.md` REQ-FE-536 ScriptDev 抽屉（不冲突）
