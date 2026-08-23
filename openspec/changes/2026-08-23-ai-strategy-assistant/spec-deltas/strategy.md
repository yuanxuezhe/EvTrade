# Spec Delta — strategy (AI 策略助手)

## REQ-STRAT-022: ScriptDev AI 策略助手 (2026-08-23, ai-strategy-assistant change)

### Purpose

让用户在 ScriptDev 页面通过自然语言描述策略需求，AI 自动生成可用的 Python 策略代码并注入到编辑器。

### Contract

- **入口**：ScriptDev 页面顶部「AI 助手」按钮 → 右侧抽屉（el-drawer）
- **输入**：用户在抽屉输入框写自然语言描述，可选附当前 `form.code`（让 AI 基于现有代码改）
- **请求**：`POST /api/ai-strategy { description: str, current_code?: str }`
- **响应**：`{ code: 0, msg: "ok", list: { python_code: str, model: str } }`
- **注入**：前端用 el-message-box.confirm 确认 → 替换 ScriptDev `form.code`

### Sandbox Boundary

- AI 仅返回 Python 代码字符串（后端正则提取 ```python ... ``` 代码块）
- AI 不得直接写 EvTrade 任何文件
- LLM 调用走 hermes serve daemon（默认 127.0.0.1:9119）+ `worktree` 隔离
- prompt 注入策略模板 + `current_code`（如有），禁止注入任意用户文件路径

### Error Handling

- hermes serve 未起 → `503 { code: -1, msg: "hermes daemon not reachable at <url>" }`
- LLM 超时（默认 60s）→ `504 { code: -2, msg: "AI generation timeout" }`
- LLM 输出无 python 代码块 → `422 { code: -3, msg: "AI did not return valid Python code" }`
- 网络/解析错误 → `500 { code: -1, msg: "<details>" }`

### Out of Scope (v1)

- 对话式多轮（v1 只单次生成）
- 流式 token 输出（v1 等完整返回）
- AI 自动保存到数据库（仅注入编辑器，由用户手动保存）
- hermes serve 启动管理（用户手动起，不纳入 evctl）

### Refs

- `openspec/changes/2026-08-23-ai-strategy-assistant/proposal.md`
- `openspec/specs/strategy/spec.md` REQ-STRAT-014~017 现行契约
