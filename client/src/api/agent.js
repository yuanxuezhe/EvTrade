/**
 * client/src/api/agent.js — AI Agent WS 客户端
 *
 * 封装 ws://host/api/agent/ws?token=<jwt> 双向通信：
 * - sendUserMessage(text): 发 user_message → 启动 hermes run
 * - respondConfirmation(pending_key, confirmed): 发 confirmation → 解析 FastAPI Future
 * - 事件回调：onReady / onStepStart / onText / onToolCall / onToolResult / onConfirmationRequired / onAgentComplete / onError
 *
 * 自动重连：WS 断开后指数退避重连（最多 5 次）。
 *
 * 协议（与 server/api/agent.py 严格对齐 — REQ-ARCH-008）：
 * Vue → FastAPI:
 *   {type: "user_message", text: "..."}
 *   {type: "confirmation", pending_key, confirmed}
 *   {type: "ping"}
 * FastAPI → Vue:
 *   {type: "ready", session_id}
 *   {type: "step_start"}
 *   {type: "text", content}
 *   {type: "tool_call", name, params}
 *   {type: "tool_result", result}
 *   {type: "confirmation_required", pending_key, name, params, ...}
 *   {type: "agent_complete"}
 *   {type: "error", message}
 *   {type: "pong"}
 */

const WS_PATH = '/api/agent/ws'
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
    // 只取 hostname（WS 应走标准 443/80，通过 nginx upgrade 转发）
    return `${proto}//${window.location.hostname}`
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
    const { type } = msg
    switch (type) {
      case 'ready':
        this.sessionId = msg.session_id
        this._emit('onReady', msg)
        if (resolveReady) resolveReady(msg)
        break
      case 'step_start':
        this._emit('onStepStart', msg)
        break
      case 'text':
        this._emit('onText', msg)
        break
      case 'tool_call':
        this._emit('onToolCall', msg)
        break
      case 'tool_result':
        this._emit('onToolResult', msg)
        break
      case 'confirmation_required':
        this._emit('onConfirmationRequired', msg)
        break
      case 'agent_complete':
        this._emit('onAgentComplete', msg)
        break
      case 'error':
        this._emit('onError', new Error(msg.message || 'agent error'))
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

  async sendUserMessage(text) {
    this._send({ type: 'user_message', text })
    // 等消息真正发出（避免 race — store 拿不到 ack）
    // 不强制等 ack，只保证已入队 / 已 send
  }

  async respondConfirmation(pendingKey, confirmed) {
    this._send({ type: 'confirmation', pending_key: pendingKey, confirmed })
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
