# Spec Delta: frontend — 删 REQ-FE-537 + REQ-FE-539

## REMOVED Requirements

### REQ-FE-537: 全局 AI 对话助手浮动按钮 (2026-08-23, ai-agent-panel change)

> ❌ 本 REQ 因 `2026-08-25-cleanup-ai-remove` change **整条删除**（右下角 AI 助手按钮 + 全链路删除）。

理由：用户拍板移除全部 AI 功能（"目前系统里面的 AI 都有问题"），后续重构时再重新设计。

**删除范围**：
- 入口组件 `client/src/components/agent/AgentPanel.vue`（浮动按钮 + 对话框）
- Store `client/src/stores/agent.js`
- API 客户端 `client/src/api/agent.js`（WS + status 探测）
- App.vue 挂载点 `<AgentPanel v-if="authStore.isAuthenticated" />`
- 路由 `/ai-analysis`（虽然走的是 REQ-FE-538，命名相近）

### REQ-FE-539: AI 助手能力探测 + 降级 UI（2026-08-25）

> ❌ 本 REQ 因 `2026-08-25-cleanup-ai-remove` change **整条删除**（`fetchAgentStatus` + `probeAgentStatus` + `agent-fab-disabled`）。

理由：随 REQ-FE-537 删除后，浮动按钮与探测均失效。

**删除范围**：
- `client/src/api/agent.js::fetchAgentStatus`
- `client/src/stores/agent.js::agentAvailable/agentUnavailableReason/probeAgentStatus`
- `client/src/components/agent/AgentPanel.vue::agent-fab-disabled` class + 提示条

## ADDED Requirements

无。

## MODIFIED Requirements

无。

## Notes

- `REQ-FE-536`（ScriptDev 单次生成助手）是 `openspec/changes/2026-08-23-ai-strategy-assistant/spec-deltas/frontend.md` 的 active draft（未合并），随 change 目录整删而失效。
- `REQ-FE-538`（useQuoteSubscription composable，2026-08-25）保留，与 AI 无关。