# Spec Delta — frontend (ScriptDev AI 抽屉)

## REQ-FE-536: ScriptDev AI 助手抽屉 (2026-08-23, ai-strategy-assistant change)

### Purpose

在 ScriptDev 页面提供 AI 助手抽屉，让用户能用自然语言描述策略需求并自动生成 Python 代码注入到 ScriptDev 编辑器。

### UI 契约

- **入口**：`ScriptDev.vue` 顶部右侧 `sd-actions` 加 `<el-button data-el="sd-ai-helper">`「🤖 AI 助手」按钮
- **抽屉**：`<el-drawer v-model="aiDrawerOpen" direction="rtl" size="420px">`
- **抽屉内**：
  - `<el-input type="textarea" v-model="aiPrompt" :rows="6" placeholder="描述你的策略…">`
  - `<el-button @click="onAiGenerate" :loading="aiGenerating">让 Hermes 生成</el-button>`
  - `<el-alert v-if="aiError" :title="aiError" type="error">`
- **生成成功**：
  - 弹 `ElMessageBox.confirm('AI 已生成策略代码, 是否注入到编辑器?')`
  - 用户确认 → `form.code = aiResult` → 关闭抽屉 → `ElMessage.success('已注入')`
  - 用户取消 → 保留抽屉 + aiResult（可继续修改 prompt 重试）

### 状态机

| 状态 | 触发 | 副作用 |
|---|---|---|
| `closed` | 默认 | 抽屉不渲染 |
| `open-empty` | 点「AI 助手」按钮 | 显示输入框 |
| `generating` | 点「生成」按钮 | 输入框 + 按钮 disable + 加载 spinner |
| `open-result` | 后端返回 | 显示 aiResult + 「再试一次」+「注入编辑器」按钮 |
| `open-error` | 后端报错 | 显示 aiError + 「重试」按钮 |
| `readonly` | 当前 ScriptDev 只读 | 整个 AI 抽屉不渲染（与 `isReadonly` 同生命周期） |

### API 客户端

- `client/src/api/ai_strategy.js` 新增：
  - `generateStrategy({ description, current_code })` → `POST /api/ai-strategy`
  - `request({ ... })` axios 封装（走已有 baseURL + JWT 拦截器）

### Out of Scope (v1)

- 对话式多轮（v1 单次生成）
- 流式 token 输出（v1 等完整返回）
- 历史持久化（v1 仅内存保留最近 1 次）
- 自动保存（v1 仅注入编辑器，由用户手动保存）

### Refs

- `openspec/changes/2026-08-23-ai-strategy-assistant/proposal.md`
- `openspec/specs/frontend/spec.md` REQ-FE-535 ScriptDev 已有契约
