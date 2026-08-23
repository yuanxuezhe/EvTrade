/**
 * client/src/stores/agent.js — Pinia store: AI Agent 全局状态
 *
 * 持有：
 * - messages: 消息列表（user / assistant_text / tool_call / thinking）
 * - pendingConfirmation: 待确认的高危 tool（Modal 用）
 * - isThinking: LLM 推理中（显示 spinner）
 * - isOpen: 浮动对话框是否展开
 * - isConnected: WS 是否连上
 * - sessionId: hermes session id
 *
 * 持久化：v1 仅内存（page reload 清空，符合 spec）。
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { AgentWSClient } from '../api/agent'

let _client = null  // 单例 WS client（跨 store action）

export const useAgentStore = defineStore('agent', () => {
  // ─── state ────────────────────────────────────────────────
  const messages = ref([])  // [{id, role, text?, toolName?, toolParams?, toolResult?, status?, createdAt}]
  const pendingConfirmation = ref(null)  // {pendingKey, name, params} | null
  const isThinking = ref(false)
  const isOpen = ref(false)
  const isConnected = ref(false)
  const sessionId = ref(null)
  const lastError = ref(null)
  const currentRunId = ref(null)

  // ─── getters ──────────────────────────────────────────────
  const hasPendingConfirmation = computed(() => pendingConfirmation.value !== null)
  const lastMessage = computed(() => messages.value[messages.value.length - 1] || null)
  const messageCount = computed(() => messages.value.length)

  // ─── actions ──────────────────────────────────────────────
  function openPanel() {
    isOpen.value = true
    if (!isConnected.value) {
      _connect()
    }
  }

  function closePanel() {
    isOpen.value = false
  }

  function togglePanel() {
    isOpen.value ? closePanel() : openPanel()
  }

  async function _connect() {
    const handlers = {
      onReady: (msg) => {
        isConnected.value = true
        sessionId.value = msg.session_id
        lastError.value = null
      },
      onStepStart: () => {
        isThinking.value = true
        currentRunId.value = currentRunId.value  // 保留 run_id（hermes event 自带 run_id）
      },
      onText: (msg) => {
        isThinking.value = false
        // 累积到最近的 assistant_text 消息（或新建一条）
        const last = lastMessage.value
        if (last && last.role === 'assistant_text' && last.runId === msg.run_id) {
          last.text = (last.text || '') + (msg.content || '')
        } else {
          messages.value.push({
            id: _nextId(),
            role: 'assistant_text',
            text: msg.content || '',
            runId: msg.run_id,
            createdAt: Date.now(),
          })
        }
      },
      onToolCall: (msg) => {
        isThinking.value = false
        messages.value.push({
          id: _nextId(),
          role: 'tool_call',
          toolName: msg.name,
          toolParams: msg.params || {},
          status: 'executing',
          runId: msg.run_id,
          createdAt: Date.now(),
        })
      },
      onToolResult: (msg) => {
        // 找最近的 tool_call 卡片更新 status + result
        for (let i = messages.value.length - 1; i >= 0; i--) {
          const m = messages.value[i]
          if (m.role === 'tool_call' && m.runId === msg.run_id && m.status === 'executing') {
            m.status = 'done'
            m.toolResult = msg.result
            break
          }
        }
      },
      onConfirmationRequired: (msg) => {
        pendingConfirmation.value = {
          pendingKey: msg.pending_key,
          name: msg.name,
          params: msg.params || {},
        }
      },
      onAgentComplete: () => {
        isThinking.value = false
        currentRunId.value = null
      },
      onError: (err) => {
        isThinking.value = false
        lastError.value = err.message || String(err)
      },
      onClose: () => {
        isConnected.value = false
      },
    }
    _client = new AgentWSClient({
      token: localStorage.getItem('evtrade-token') || '',
      handlers,
    })
    try {
      await _client.connect()
    } catch (e) {
      lastError.value = `WS connect failed: ${e.message}`
    }
  }

  async function sendUserMessage(text) {
    if (!text || !text.trim()) return
    // 1. 先确保 WS 连上（如果还没连就 await，连上后再发）
    if (!_client) {
      await _connect()
    } else if (!_client.readyPromise) {
      // WS 之前连接已断开 → 重连
      try {
        await _client.connect()
      } catch (e) {
        lastError.value = `WS reconnect failed: ${e.message}`
        return
      }
    } else if (_client.readyPromise) {
      // WS 正在连 → 等连上
      try {
        await _client.readyPromise
      } catch (e) {
        lastError.value = `WS connect failed: ${e.message}`
        return
      }
    }

    // 2. 入消息 + 发（_send 会保证 WS OPEN 才真发出，未连上则入队等 ready 事件 flush）
    messages.value.push({
      id: _nextId(),
      role: 'user',
      text,
      createdAt: Date.now(),
    })
    await _client.sendUserMessage(text)
  }

  async function respondConfirmation(confirmed) {
    if (!_client || !pendingConfirmation.value) return
    await _client.respondConfirmation(pendingConfirmation.value.pendingKey, confirmed)
    pendingConfirmation.value = null
  }

  function clearMessages() {
    messages.value = []
    pendingConfirmation.value = null
    lastError.value = null
  }

  function disconnect() {
    if (_client) {
      _client.close()
      _client = null
    }
    isConnected.value = false
    sessionId.value = null
  }

  return {
    // state
    messages,
    pendingConfirmation,
    isThinking,
    isOpen,
    isConnected,
    sessionId,
    lastError,
    currentRunId,
    // getters
    hasPendingConfirmation,
    lastMessage,
    messageCount,
    // actions
    openPanel,
    closePanel,
    togglePanel,
    sendUserMessage,
    respondConfirmation,
    clearMessages,
    disconnect,
  }
})

let _msgId = 0
function _nextId() {
  _msgId += 1
  return `msg-${_msgId}-${Date.now()}`
}
