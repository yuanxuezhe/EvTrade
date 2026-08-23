<!--
  AgentPanel.vue — 全局右下角 AI 对话助手浮动按钮 + 悬浮对话框 (ai-agent-panel)

  设计：右下角固定按钮，点击 → 右下角弹出 480×600 悬浮对话框（不是 el-drawer）。
  所有页面全局可见（在 App.vue 挂载）。
  通过 Pinia agent store 拿 WS 状态 + 消息列表。

  Spec: openspec/specs/frontend/spec.md REQ-FE-537
-->
<template>
  <div class="agent-panel-root" data-el="agent-panel-root">
    <!-- 浮动按钮 (右下角 fixed) -->
    <button
      v-if="!store.isOpen"
      class="agent-fab"
      data-el="agent-fab"
      title="AI 助手"
      @click="store.openPanel()"
    >
      <el-icon class="agent-fab-icon"><MagicStick /></el-icon>
      <span class="agent-fab-text">🤖 AI</span>
      <span v-if="store.hasPendingConfirmation" class="agent-fab-badge">!</span>
    </button>

    <!-- 悬浮对话框 (右下角 fixed, 480×600) -->
    <div v-if="store.isOpen" class="agent-panel" data-el="agent-panel">
      <header class="agent-header">
        <h3 class="agent-title">
          <el-icon><MagicStick /></el-icon>
          AI 助手
        </h3>
        <div class="agent-header-actions">
          <span
            class="agent-status"
            :class="store.isConnected ? 'connected' : 'disconnected'"
            :title="store.isConnected ? '已连接 hermes' : '未连接'"
          >●</span>
          <el-button text size="small" @click="store.clearMessages()">清空</el-button>
          <el-button text size="small" @click="store.closePanel()">×</el-button>
        </div>
      </header>

      <!-- 消息列表 -->
      <div class="agent-messages" ref="msgListRef" data-el="agent-messages">
        <div
          v-for="msg in store.messages"
          :key="msg.id"
          class="agent-msg"
          :class="msg.role"
        >
          <!-- User -->
          <div v-if="msg.role === 'user'" class="msg-bubble user">
            {{ msg.text }}
          </div>

          <!-- Assistant text -->
          <div v-else-if="msg.role === 'assistant_text'" class="msg-bubble assistant">
            <pre class="msg-text">{{ msg.text }}</pre>
          </div>

          <!-- Tool call 卡片 -->
          <div v-else-if="msg.role === 'tool_call'" class="msg-tool-card">
            <header class="tool-header">
              <el-icon><Tools /></el-icon>
              <strong>{{ msg.toolName }}</strong>
              <el-tag size="small" :type="msg.status === 'done' ? 'success' : 'warning'">
                {{ msg.status }}
              </el-tag>
            </header>
            <details v-if="msg.toolParams && Object.keys(msg.toolParams).length" class="tool-details">
              <summary>参数</summary>
              <pre>{{ JSON.stringify(msg.toolParams, null, 2) }}</pre>
            </details>
            <details v-if="msg.toolResult" class="tool-details" open>
              <summary>结果</summary>
              <pre>{{ formatJson(msg.toolResult) }}</pre>
            </details>
          </div>
        </div>

        <!-- Thinking spinner -->
        <div v-if="store.isThinking" class="msg-thinking">
          <el-icon class="rotating"><Loading /></el-icon>
          <span>AI 思考中...</span>
        </div>

        <!-- 错误 -->
        <div v-if="store.lastError" class="msg-error" data-el="agent-error">
          �️ {{ store.lastError }}
        </div>

        <!-- 空状态 -->
        <div v-if="store.messageCount === 0 && !store.lastError" class="msg-empty">
          <p>输入指令, 例如:</p>
          <ul>
            <li>"查一下我的持仓"</li>
            <li>"600000.SH 现在多少钱"</li>
            <li>"帮我下单 100 股 600000.SH"</li>
          </ul>
        </div>
      </div>

      <!-- 输入框 -->
      <footer class="agent-input">
        <el-input
          v-model="inputText"
          type="textarea"
          :rows="2"
          placeholder="输入指令 (Ctrl+Enter 发送)"
          :disabled="store.hasPendingConfirmation"
          @keydown="onKeydown"
          data-el="agent-input"
        />
        <el-button
          type="primary"
          :icon="Promotion"
          :loading="store.isThinking"
          :disabled="!inputText.trim() || store.hasPendingConfirmation"
          @click="onSend"
          data-el="agent-send"
        >发送</el-button>
      </footer>
    </div>

    <!-- 二次确认 Modal (高危 tool) -->
    <el-dialog
      v-model="confirmDialogVisible"
      title="⚠️ 高危操作确认"
      width="480px"
      :close-on-click-modal="false"
      data-el="agent-confirm-modal"
    >
      <div v-if="store.pendingConfirmation">
        <p>AI 想要执行以下操作:</p>
        <p class="confirm-tool-name"><strong>{{ store.pendingConfirmation.name }}</strong></p>
        <pre class="confirm-params">{{ formatJson(store.pendingConfirmation.params) }}</pre>
        <p class="confirm-warning">⚠️ 此操作将立即生效, 请确认是否继续</p>
      </div>
      <template #footer>
        <el-button @click="onReject" data-el="agent-confirm-reject">拒绝</el-button>
        <el-button type="danger" @click="onConfirm" data-el="agent-confirm-accept">确认执行</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, watch, nextTick, computed } from 'vue'
import { MagicStick, Tools, Loading, Promotion } from '@element-plus/icons-vue'
import { useAgentStore } from '../../stores/agent'

const store = useAgentStore()
const inputText = ref('')
const msgListRef = ref(null)
const confirmDialogVisible = computed(() => store.hasPendingConfirmation)

// ─── 自动滚动到底部 ─────────────────────────────────────────
watch(() => store.messages.length, async () => {
  await nextTick()
  if (msgListRef.value) {
    msgListRef.value.scrollTop = msgListRef.value.scrollHeight
  }
})

// ─── 发送 ──────────────────────────────────────────────────────
async function onSend() {
  const text = inputText.value.trim()
  if (!text) return
  await store.sendUserMessage(text)
  inputText.value = ''
}

function onKeydown(e) {
  if (e.ctrlKey && e.key === 'Enter') {
    e.preventDefault()
    onSend()
  }
}

// ─── 二次确认 ──────────────────────────────────────────────────
function onConfirm() {
  store.respondConfirmation(true)
}
function onReject() {
  store.respondConfirmation(false)
}

// ─── helper ───────────────────────────────────────────────────
function formatJson(obj) {
  try {
    return JSON.stringify(obj, null, 2)
  } catch (e) {
    return String(obj)
  }
}
</script>

<style scoped>
.agent-panel-root {
  /* 容器 — 不影响布局 */
}

/* ─── 浮动按钮 (右下角 fixed) ──────────────────────────────── */
.agent-fab {
  position: fixed;
  bottom: 24px;
  right: 24px;
  z-index: 9999;
  display: flex;
  align-items: center;
  gap: 6px;
  height: 56px;
  padding: 0 20px;
  border: none;
  border-radius: 28px;
  background: linear-gradient(135deg, var(--brand-primary, #409eff), var(--brand-secondary, #67c23a));
  color: white;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  box-shadow: 0 6px 20px rgba(64, 158, 255, 0.4);
  transition: transform 200ms, box-shadow 200ms;
}
.agent-fab:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 28px rgba(64, 158, 255, 0.5);
}
.agent-fab-icon {
  font-size: 22px;
}
.agent-fab-badge {
  position: absolute;
  top: 6px;
  right: 8px;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: #f56c6c;
  color: white;
  font-size: 11px;
  line-height: 18px;
  text-align: center;
  animation: pulse 1.5s infinite;
}
@keyframes pulse {
  0%, 100% { transform: scale(1); }
  50% { transform: scale(1.2); }
}

/* ─── 悬浮对话框 (右下角 fixed, 480×600) ──────────────────── */
.agent-panel {
  position: fixed;
  bottom: 96px;
  right: 24px;
  z-index: 9998;
  width: 480px;
  height: 600px;
  display: flex;
  flex-direction: column;
  background: var(--bg-card, #fff);
  border: 1px solid var(--border-base, #e4e7ed);
  border-radius: 12px;
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.15);
  overflow: hidden;
}

.agent-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-light, #ebeef5);
  background: var(--bg-page, #fafafa);
}
.agent-title {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 0;
  font-size: 14px;
  font-weight: 600;
}
.agent-header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.agent-status {
  font-size: 10px;
  color: #f56c6c;
}
.agent-status.connected {
  color: #67c23a;
}

/* ─── 消息列表 ───────────────────────────────────────────── */
.agent-messages {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
  background: var(--bg-page, #fafafa);
}
.agent-msg {
  margin-bottom: 10px;
}
.msg-bubble {
  padding: 8px 12px;
  border-radius: 8px;
  max-width: 85%;
  word-break: break-word;
}
.msg-bubble.user {
  margin-left: auto;
  background: var(--brand-primary, #409eff);
  color: white;
}
.msg-bubble.assistant {
  background: var(--bg-card, #fff);
  border: 1px solid var(--border-light, #ebeef5);
}
.msg-text {
  margin: 0;
  font-family: inherit;
  font-size: 13px;
  line-height: 1.5;
  white-space: pre-wrap;
}
.msg-tool-card {
  border: 1px solid var(--border-light, #ebeef5);
  border-radius: 6px;
  padding: 8px;
  background: var(--bg-card, #fff);
}
.tool-header {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
}
.tool-details {
  margin-top: 4px;
  font-size: 11px;
}
.tool-details summary {
  cursor: pointer;
  color: var(--color-text-secondary, #909399);
}
.tool-details pre {
  margin: 4px 0 0;
  padding: 6px;
  background: var(--bg-page, #fafafa);
  border-radius: 4px;
  font-size: 11px;
  overflow-x: auto;
}
.msg-thinking {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  color: var(--color-text-secondary, #909399);
  font-size: 12px;
}
.rotating {
  animation: spin 1s linear infinite;
}
@keyframes spin {
  100% { transform: rotate(360deg); }
}
.msg-error {
  padding: 8px 12px;
  background: #fef0f0;
  border: 1px solid #fbc4c4;
  border-radius: 6px;
  color: #f56c6c;
  font-size: 12px;
}
.msg-empty {
  padding: 20px 12px;
  color: var(--color-text-secondary, #909399);
  font-size: 12px;
}
.msg-empty ul {
  margin: 6px 0 0;
  padding-left: 18px;
}

/* ─── 输入框 ────────────────────────────────────────────── */
.agent-input {
  display: flex;
  gap: 8px;
  padding: 10px 12px;
  border-top: 1px solid var(--border-light, #ebeef5);
  background: var(--bg-card, #fff);
}

/* ─── 二次确认 Modal ────────────────────────────────────── */
.confirm-tool-name {
  font-size: 16px;
  margin: 8px 0;
}
.confirm-params {
  background: var(--bg-page, #fafafa);
  padding: 10px;
  border-radius: 4px;
  font-size: 12px;
  overflow-x: auto;
  max-height: 200px;
}
.confirm-warning {
  color: #f56c6c;
  font-size: 13px;
  margin-top: 12px;
}

/* ─── 移动端 ────────────────────────────────────────────── */
@media (max-width: 768px) {
  .agent-panel {
    width: calc(100vw - 32px);
    height: 70vh;
    bottom: 88px;
    right: 16px;
  }
  .agent-fab {
    right: 16px;
    bottom: 16px;
  }
}
</style>
