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
import { AgentWSClient, fetchAgentStatus } from '../api/agent'

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
  // 2026-08-25 增补 (REQ-FE-539): AI 助手可用性探测状态
  // - agentAvailable: 后端 /api/ai/status 探测结果, 默认 true (向后兼容: 探测失败时保持原行为)
  // - agentUnavailableReason: 不可用时给前端的 tooltip / 提示语
  // - agentStatusLoaded: 是否已完成首次探测 (避免面板打开前按钮闪烁)
  const agentAvailable = ref(true)
  const agentUnavailableReason = ref('')
  const agentStatusLoaded = ref(false)

  // ─── getters ──────────────────────────────────────────────
  const hasPendingConfirmation = computed(() => pendingConfirmation.value !== null)
  const lastMessage = computed(() => messages.value[messages.value.length - 1] || null)
  const messageCount = computed(() => messages.value.length)

  // ─── actions ──────────────────────────────────────────────
  // 2026-08-25 增补: 探测后端 /api/ai/status, 决定 agentAvailable
  async function probeAgentStatus() {
    const result = await fetchAgentStatus()
    agentAvailable.value = result.available
    agentUnavailableReason.value = result.reason || ''
    agentStatusLoaded.value = true
  }

  function openPanel() {
    isOpen.value = true
    // 2026-08-25 增补: 打开前先探测 AI 可用性; 不可用时不连 WS, 直接展示降级提示
    if (!agentStatusLoaded.value) {
      probeAgentStatus().then(() => {
        if (!agentAvailable.value) {
          lastError.value = agentUnavailableReason.value
          // 不调 _connect(), 让按钮保持灰显状态
        } else if (!isConnected.value) {
          _connect()
        }
      })
    } else if (agentAvailable.value && !isConnected.value) {
      _connect()
    } else if (!agentAvailable.value) {
      lastError.value = agentUnavailableReason.value
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
      onRunStarted: (msg) => {
        isThinking.value = true
        currentRunId.value = msg.run_id
      },
      onMessageDelta: (msg) => {
        // Hermes message.delta — token 级流式文本（累积到最近 assistant_text）
        isThinking.value = false
        const last = lastMessage.value
        const delta = msg.delta || ''
        if (!delta) return
        if (last && last.role === 'assistant_text' && last.runId === msg.run_id) {
          last.text = (last.text || '') + delta
        } else {
          messages.value.push({
            id: _nextId(),
            role: 'assistant_text',
            text: delta,
            runId: msg.run_id,
            messageId: msg.message_id,
            createdAt: Date.now(),
          })
        }
      },
      onReasoningAvailable: (msg) => {
        // Hermes reasoning.available — LLM 内部推理文本
        isThinking.value = false
        messages.value.push({
          id: _nextId(),
          role: 'thinking',
          text: msg.text || '',
          runId: msg.run_id,
          messageId: msg.message_id,
          createdAt: Date.now(),
        })
      },
      onText: (msg) => {
        // 兜底：旧 assistant.completed 事件（spec 写的字段名）也支持
        isThinking.value = false
        const last = lastMessage.value
        if (last && last.role === 'assistant_text' && last.runId === msg.run_id) {
          last.text = (last.text || '') + (msg.content || '')
        } else {
          messages.value.push({
            id: _nextId(),
            role: 'assistant_text',
            text: msg.content || '',
            runId: msg.run_id,
            messageId: msg.message_id,
            createdAt: Date.now(),
          })
        }
      },
      onToolCall: (msg) => {
        // Hermes tool.started — 实际字段名：tool（不是 tool_name）, preview（不是 args）
        isThinking.value = false
        messages.value.push({
          id: _nextId(),
          role: 'tool_call',
          toolName: msg.tool || msg.tool_name,
          toolParams: msg.args || {},
          preview: msg.preview,
          status: 'executing',
          runId: msg.run_id,
          messageId: msg.message_id,
          createdAt: Date.now(),
        })
      },
      onToolCompleted: (msg) => {
        // Hermes tool.completed — 字段名 tool；error=true 时算 failed
        const errorFlag = msg.error === true
        for (let i = messages.value.length - 1; i >= 0; i--) {
          const m = messages.value[i]
          if (m.role === 'tool_call' && m.runId === msg.run_id && m.status === 'executing') {
            m.status = errorFlag ? 'failed' : 'done'
            m.toolResult = msg.result || (errorFlag ? { error: msg.error_message || 'tool failed' } : null)
            m.duration = msg.duration
            break
          }
        }
      },
      onToolFailed: (msg) => {
        for (let i = messages.value.length - 1; i >= 0; i--) {
          const m = messages.value[i]
          if (m.role === 'tool_call' && m.runId === msg.run_id && m.status === 'executing') {
            m.status = 'failed'
            m.toolResult = { error: msg.error || 'tool failed' }
            break
          }
        }
      },
      onApprovalRequired: (msg) => {
        // Hermes approval.required — 字段名 pending_key + tool（兼容 tool_name）+ args
        pendingConfirmation.value = {
          pendingKey: msg.pending_key,
          runId: msg.run_id,
          name: msg.tool || msg.tool_name,
          params: msg.args || {},
        }
      },
      onRunCompleted: () => {
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
    const { pendingKey, runId } = pendingConfirmation.value
    // 二次确认 choice：true→once（执行一次），false→deny（拒绝）
    const choice = confirmed ? 'once' : 'deny'
    await _client.respondApproval(runId, pendingKey, choice)
    pendingConfirmation.value = null
  }

  async function stopCurrentRun() {
    if (!_client || !currentRunId.value) return
    await _client.stopRun(currentRunId.value)
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
    agentAvailable,           // 2026-08-25
    agentUnavailableReason,   // 2026-08-25
    agentStatusLoaded,        // 2026-08-25
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
    stopCurrentRun,
    clearMessages,
    disconnect,
    probeAgentStatus,         // 2026-08-25
  }
})

let _msgId = 0
function _nextId() {
  _msgId += 1
  return `msg-${_msgId}-${Date.now()}`
}
