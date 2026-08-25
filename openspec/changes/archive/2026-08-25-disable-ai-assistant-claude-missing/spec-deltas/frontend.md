# Spec Delta — frontend (2026-08-25-disable-ai-assistant-claude-missing)

## REQ-FE-539: AI 助手能力探测 + 降级 UI

### 触发
后端 `claude` CLI 缺失（环境差异 / 容器未装 / 用户手动卸载）。

### 行为
1. **加载时探测**：Vue 应用 mount 时 `useAgentStore` 调 `fetchAgentStatus()` → 拿到 `agentAvailable: bool` + `agentUnavailableReason: string`
2. **浮动按钮**：`!agentAvailable` 时按钮 `:disabled="true"` + 灰显 + hover tooltip `agentUnavailableReason`
3. **面板 header**：打开面板时若不可用，header 加红色提示条 `AI 助手暂不可用：<reason>`
4. **store.openPanel()**：探测前先 await `fetchAgentStatus()`；不可用时直接 set `lastError = reason`，**不连 WS**
5. **探测失败**：fetch 异常时默认 `agentAvailable=true`（保持原行为，最坏回到 WS 错误兜底路径）

### 实现位置
- `client/src/api/agent.js` 加 `fetchAgentStatus()`（fetch GET `/api/ai/status`）
- `client/src/stores/agent.js` 加 `agentAvailable` + `agentUnavailableReason` state
- `client/src/components/agent/AgentPanel.vue` 浮动按钮加 `:disabled` + tooltip

### 测试
- 前端不强制单测（项目惯例）；后端 `/api/ai/status` 端点单测覆盖即可
- 手动 e2e：浏览器 DevTools 看 `/api/ai/status` 响应 → 按钮 disabled 行为

### 范围
- 不动消息渲染 / ConfirmRegistry / WS 协议
- 不动 `AgentPanel.vue` 整体布局