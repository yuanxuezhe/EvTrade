/**
 * client/src/api/agent.js — AI Agent WS 客户端
 *
 * 封装 ws://host/ws/agent_channel?token=<jwt> 双向通信：
 * - sendUserMessage(text, sessionId?): 发 user_message → FastAPI 调 Hermes /v1/runs
 * - respondApproval(runId, pendingKey, choice): 发 confirmation → FastAPI 调 /v1/runs/{id}/approval
 * - stopRun(runId): 发 stop → FastAPI 调 /v1/runs/{id}/stop
 * - 事件回调：onReady / onRunStarted / onText / onToolCall / onToolCompleted /
 *              onApprovalRequired / onRunCompleted / onError
 *
 * 自动重连：WS 断开后指数退避重连（最多 5 次）。
 *
 * 协议（2026-08-23, upgrade-agent-to-v1-runs change — REQ-ARCH-008 重写）：
 * Vue → FastAPI:
 *   {type: "user_message", text: "..."}
 *   {type: "confirmation", run_id, pending_key, choice}
 *   {type: "stop", run_id}
 *   {type: "ping"}
 * FastAPI → Vue（事件名对齐 Hermes API server SSE）:
 *   {type: "ready", session_id}
 *   {type: "run.started", run_id, session_id}
 *   {type: "message.started", message_id, message}
 *   {type: "tool.progress", tool_name, delta}
 *   {type: "tool.started", tool_name, preview, args}
 *   {type: "tool.completed", tool_name, preview, args, result}
 *   {type: "tool.failed", tool_name, error}
 *   {type: "assistant.completed", message_id, content}
 *   {type: "run.completed", session_id, message_id, usage}
 *   {type: "approval.required", pending_key, tool_name, args}
 *   {type: "error", message, run_id?}
 *   {type: "done"}
 *   {type: "pong"}
 */

const WS_PATH = '/ws/agent_channel'  // 2026-08-23, ai-agent-ws-reuse-channel — 共用 /ws/{channel}
const MAX_RECONNECT = 5
const BASE_BACKOFF_MS = 500  // 指数退避起点

export class AgentWSClient {
  /**
   * @param {object} opts
   * @param {string} opts.token — JWT
   * @param {string} [opts.wsBase] — WS base URL, 默认从 window.location 推导 (ws://host 或 wss://host)
   * @param {object} opts.handlers — 事件回调
   */
  constructor({ token, wsBase, handlers = {} }) {
    this.token = token
    this.wsBase = wsBase || this._deriveWSBase()
    this.handlers = handlers
    this.ws = null
    this.reconnectAttempts = 0
    this.shouldReconnect = true
    this.sessionId = null
    this.lastEvent = null
    this.readyPromise = null  // Promise resolves when WS is OPEN + ready event arrived
    this.messageQueue = []  // messages buffered before WS ready
  }

  _deriveWSBase() {
    // 优先用环境变量（Vite 注入），否则从当前页面推导
    const envBase = (import.meta?.env?.VITE_AGENT_WS_BASE || '').trim()
    if (envBase) return envBase.replace(/\/+$/, '')
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    // 与 ws_heartbeat._wsUrl / api.createWSConnection 保持一致：用 host（含端口），
    // 公网反代端口 50443 必须在 URL 里，否则 WS 落到 443 无升级 → 连接失败
    return `${proto}//${window.location.host}`
  }

  /**
   * 让外部显式覆盖 WS base URL（用于绕过 nginx WS 不可用的情况）。
   * 例如直接连后端 8000：client.setWsBaseOverride('ws://backend-host:8000')
   */
  setWsBaseOverride(wsBase) {
    if (this.ws) {
      this.close()
    }
    this.wsBase = wsBase.replace(/\/+$/, '')
    this.readyPromise = null
  }

  /**
   * 启动 WS 连接 + 注册事件分发。
   * Returns Promise that resolves when first 'ready' event arrives.
   * Subsequent calls return the same Promise (避免重复 connect).
   */
  connect() {
    // 复用现有 connect promise（避免重复建连）
    if (this.readyPromise) return this.readyPromise

    const url = `${this.wsBase}${WS_PATH}?token=${encodeURIComponent(this.token)}`
    this.readyPromise = new Promise((resolve, reject) => {
      let readyResolved = false
      try {
        this.ws = new WebSocket(url)
      } catch (e) {
        this.readyPromise = null
        reject(new Error(`WS construct failed: ${e.message}`))
        return
      }

      this.ws.onopen = () => {
        this.reconnectAttempts = 0
        this._emit('onOpen')
        // onopen 不算"ready"（FastAPI 还要发 ready 事件）— 等 ready 事件才 flush queue
      }

      this.ws.onmessage = (event) => {
        let msg
        try {
          msg = JSON.parse(event.data)
        } catch (e) {
          return
        }
        this.lastEvent = msg
        this._dispatch(msg, resolve, () => { readyResolved = true })
        // ready 事件到达 → flush 队列
        if (msg.type === 'ready') {
          this._flushQueue()
        }
      }

      this.ws.onerror = (e) => {
        this._emit('onError', e)
        if (!readyResolved) {
          readyResolved = true
          this.readyPromise = null
          reject(new Error('WS connection error'))
        }
      }

      this.ws.onclose = (e) => {
        this._emit('onClose', e)
        this.readyPromise = null  // 下次 connect 可重试
        if (this.shouldReconnect && this.reconnectAttempts < MAX_RECONNECT) {
          this._scheduleReconnect()
        }
      }
    })
    return this.readyPromise
  }

  _flushQueue() {
    while (this.messageQueue.length > 0) {
      const payload = this.messageQueue.shift()
      try {
        this.ws.send(JSON.stringify(payload))
      } catch (e) {
        console.error('[AgentWS] flush queue failed:', e)
        // send 失败时把消息放回队首（避免丢消息）
        this.messageQueue.unshift(payload)
        break
      }
    }
  }

  _dispatch(msg, resolveReady, isReady) {
    // 2026-08-24 重做 (claudedemo 模式): 后端推 claudedemo 协议事件 (text/tool_call/tool_result/agent_complete),
    // 归一化层把字段名映射到前端 store 期望的 Hermes 协议 (tool_name→tool, input→args, run_id 透传)
    // 前端 store / AgentPanel.vue 不动, 只这一层做兼容.
    const { type } = msg
    const norm = _normalizeEvent(msg)
    switch (type) {
      case 'ready':
        this.sessionId = msg.session_id
        this._emit('onReady', msg)
        if (resolveReady) resolveReady(msg)
        break
      case 'run.started':
        this._emit('onRunStarted', norm)
        break
      case 'message.started':
        this._emit('onMessageStarted', norm)
        break
      case 'message.delta':
        this._emit('onMessageDelta', norm)
        break
      case 'reasoning.available':
        this._emit('onReasoningAvailable', norm)
        break
      case 'tool.progress':
        this._emit('onToolProgress', norm)
        break
      case 'text':
        // claudedemo AgentEvent(type='text', payload={text}) → 转成 assistant_text delta
        // store.onText 期望 msg.content, 我们让 normalize 透传 + 加 content 字段
        this._emit('onText', norm)
        break
      case 'tool_call':
        // claudedemo AgentEvent(type='tool_call', payload={name, input, id})
        // → 转成 tool.started 等价, 字段: tool (name), args (input), preview (input 序列化), id
        this._emit('onToolCall', norm)
        break
      case 'tool_result':
        // claudedemo AgentEvent(type='tool_result', payload={id, content, is_error})
        // → 转成 tool.completed, 字段: id, result (content), is_error
        this._emit('onToolCompleted', norm)
        break
      case 'agent_complete':
        // claudedemo AgentEvent(type='agent_complete', payload={success, result, error, usage})
        // → 转成 run.completed, 字段: success, result, error, usage
        this._emit('onRunCompleted', norm)
        break
      case 'approval.required':
        this._emit('onApprovalRequired', msg)
        break
      case 'approval.responded':
        this._emit('onApprovalResponded', msg)
        break
      case 'run.completed':
        this._emit('onRunCompleted', msg)
        break
      case 'error':
        this._emit('onError', new Error(msg.message || 'agent error'))
        break
      case 'done':
        // 流结束标记 — store 忽略即可
        break
      case 'pong':
        this._emit('onPong', msg)
        break
      default:
        // 未知 type → 静默忽略
        break
    }
  }

  _emit(name, payload) {
    const fn = this.handlers[name]
    if (typeof fn === 'function') {
      try { fn(payload) } catch (e) { console.error(`[AgentWS] handler ${name} threw:`, e) }
    }
  }

  _scheduleReconnect() {
    this.reconnectAttempts += 1
    const delay = BASE_BACKOFF_MS * Math.pow(2, this.reconnectAttempts - 1)
    setTimeout(() => {
      if (!this.shouldReconnect) return
      this.connect().catch((e) => {
        this._emit('onError', e)
      })
    }, delay)
  }

  _send(payload) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      // WS 未就绪 → 入队，等 ready 事件自动 flush
      this.messageQueue.push(payload)
      return
    }
    try {
      this.ws.send(JSON.stringify(payload))
    } catch (e) {
      // send 失败 → 入队，下次 flush 重试
      this.messageQueue.push(payload)
      console.error('[AgentWS] _send failed, queued:', e)
    }
  }

  async sendUserMessage(text, sessionId) {
    this._send({ type: 'user_message', text, session_id: sessionId })
  }

  async respondApproval(runId, pendingKey, choice = 'deny') {
    this._send({
      type: 'confirmation',
      run_id: runId,
      pending_key: pendingKey,
      choice,
    })
  }

  async stopRun(runId) {
    this._send({ type: 'stop', run_id: runId })
  }

  ping() {
    this._send({ type: 'ping' })
  }

  close() {
    this.shouldReconnect = false
    if (this.ws) {
      try { this.ws.close() } catch (e) { /* ignore */ }
      this.ws = null
    }
  }
}

// 便利函数：从 localStorage 取 token 建 client（带默认 handlers 为 no-op）
export function createAgentClient(handlers, { wsBase } = {}) {
  const token = localStorage.getItem('evtrade-token') || ''
  return new AgentWSClient({ token, wsBase, handlers })
}


// ────────────────────────────────────────────────────────────────────────
// 2026-08-24 claudedemo 协议归一化层
// 后端 server/ai/agent_spawner.py 推 AgentEvent(type=..., payload={...}),
// 字段名是 claudedemo 风格 (name/input/content/text).
// 前端 store (stores/agent.js) 期望 Hermes 协议字段 (tool/args/run_id/message_id).
//
// _normalizeEvent 把单个 msg 复制 + 字段重命名, 不改原 msg.
// 字段映射:
//   AgentEvent.text          → msg.content (前端 onText 读 content)
//   AgentEvent.tool_call      → msg.tool (name→tool), msg.args (input→args), msg.preview (input JSON.stringify)
//   AgentEvent.tool_result    → msg.result (content→result), msg.is_error 透传
//   AgentEvent.agent_complete → msg.success, msg.result, msg.error, msg.usage 透传
//   其余事件原样透传
// ────────────────────────────────────────────────────────────────────────
function _normalizeEvent(msg) {
  if (!msg || typeof msg !== 'object') return msg
  const out = { ...msg }
  switch (msg.type) {
    case 'text':
      // AgentEvent payload={:text} → 前端 onText 期望 msg.content
      if (typeof msg.text === 'string' && msg.content === undefined) {
        out.content = msg.text
      }
      break
    case 'tool_call':
      // payload={:name, :input, :id}
      if (msg.name !== undefined && out.tool === undefined) out.tool = msg.name
      if (msg.input !== undefined && out.args === undefined) out.args = msg.input
      if (msg.input !== undefined && out.preview === undefined) {
        try { out.preview = typeof msg.input === 'string' ? msg.input : JSON.stringify(msg.input) } catch (_) { out.preview = '' }
      }
      if (msg.id !== undefined && out.tool_use_id === undefined) out.tool_use_id = msg.id
      break
    case 'tool_result':
      // payload={:id, :content, :is_error}
      if (msg.id !== undefined && out.tool_use_id === undefined) out.tool_use_id = msg.id
      if (msg.content !== undefined && out.result === undefined) out.result = msg.content
      // is_error 已透传
      break
    case 'agent_complete':
      // payload={:success, :result, :error, :usage} — 全部已直接对齐, 透传即可
      break
    default:
      // ready / run.started / error / 其他 — 原样
      break
  }
  return out
}
