/**
 * ws_heartbeat.js — WebSocket 连接 / 重连 / 心跳管理
 *
 * 职责:
 * - WS URL 构造 (含 hqserver 直连 quote_update 特例)
 * - 3 个 channel 的 _openChannel / _scheduleReconnect（order_update / trade_update + quote_update）
 *   change consolidate-position-data-flow:
 *     position_update / asset_update channel 已删除
 *     (xtquant broker 不发 pos_cfm / ast_cfm, 改由 day-init reconcile + holdings 内存缓存)
 * - 客户端主动 30s ping, 累计 3 次 (90s) 未回 pong 触发重连
 * - 指数退避: delay = min(1000 * 2^retryCount, 30000)
 *
 * 暴露 createWsManager() 工厂, 返回 { connect, disconnect, connected (ref), lastEvent (ref) }
 * 通过依赖注入 onMessage 回调（ws_dispatch.dispatchPayload）, 不直接 import dispatch
 */
import { ref } from 'vue'

export const CHANNELS = ['order_update', 'trade_update', 'quote_update']

// v7 改: WS 重连从固定 3s 改为指数退避
//   delay = min(1000 * 2^retryCount, 30000)
//   broker 长时间故障时不会 3s 一次疯狂重连
export const RECONNECT_BASE_DELAY = 1000
export const RECONNECT_MAX_DELAY = 30000

// 行情直连 hqserver :8765，不再走 server 后端转发
const QUOTE_WS_HOST = (() => {
  // 优先用环境变量；否则复用当前 host（hqserver 通常跟前端同机部署）
  if (typeof import.meta !== 'undefined' && import.meta.env?.VITE_QUOTE_WS_URL) {
    return import.meta.env.VITE_QUOTE_WS_URL.replace(/^ws/, '')
  }
  return window.location.hostname + ':8765'
})()

function _wsUrl(channel) {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  // quote_update 直连 hqserver；其他 channel 走后端
  if (channel === 'quote_update') {
    return `${proto}://${QUOTE_WS_HOST}/`
  }
  // 后端 WS 需要 JWT token（查询参数）
  const token = localStorage.getItem('evtrade-token') || ''
  const sep = token ? '?' : ''  // 第一个 query 参数用 ?，不是 &
  return `${proto}://${window.location.host}/ws/${channel}${sep}token=${encodeURIComponent(token)}`
}

/**
 * 工厂: 创建一个 ws manager 实例
 *
 * @param {Function} onMessage  payload → void（业务分发回调，注入 ws_dispatch.dispatchPayload）
 * @returns {{connect, disconnect, connected, lastEvent}}
 */
export function createWsManager(onMessage) {
  const connected = ref(false)
  const lastEvent = ref(null)
  const _sockets = {}    // channel -> WebSocket
  const _reconnectTimer = {}
  const _retryCount = {}  // v7 增: 指数退避计数, per-channel
  const _heartbeatTimer = {}  // v10 增: 客户端主动 ping 定时器, per-channel
  const _pongMissed = {}      // v10 增: 累计未回 pong 次数, per-channel

  function _openChannel(channel) {
    if (_sockets[channel] && _sockets[channel].readyState === WebSocket.OPEN) {
      return
    }
    const ws = new WebSocket(_wsUrl(channel))
    _sockets[channel] = ws

    ws.onopen = () => {
      connected.value = true
      _retryCount[channel] = 0  // v7 增: 连接成功重置退避计数
      _pongMissed[channel] = 0  // v10 增: 重置 pong 计数
      // eslint-disable-next-line no-console
      console.log(`[WS] ${channel} connected`)
      // v10 增: 客户端 30s 主动 ping（quote_update 走 hqserver 不需要）
      if (channel !== 'quote_update' && !_heartbeatTimer[channel]) {
        _heartbeatTimer[channel] = setInterval(() => {
          if (_sockets[channel]?.readyState === WebSocket.OPEN) {
            try {
              _sockets[channel].send(JSON.stringify({ type: 'ping', ts: Date.now() }))
              _pongMissed[channel] = (_pongMissed[channel] || 0) + 1
              // 连续 3 次 (90s) 没回 pong → 主动断开触发重连
              if (_pongMissed[channel] >= 3) {
                console.warn(`[WS] ${channel} pong missed ${_pongMissed[channel]}x, force close`)
                _sockets[channel]?.close()
              }
            } catch (_) { /* 忽略发送失败 */ }
          }
        }, 30000)
      }
    }

    ws.onclose = () => {
      // v7 改: 指数退避
      const c = (_retryCount[channel] || 0) + 1
      _retryCount[channel] = c
      const delay = Math.min(RECONNECT_BASE_DELAY * 2 ** (c - 1), RECONNECT_MAX_DELAY)
      // eslint-disable-next-line no-console
      console.log(`[WS] ${channel} closed, reconnect in ${delay}ms (attempt #${c})`)
      // v10 增: 清理心跳定时器
      if (_heartbeatTimer[channel]) {
        clearInterval(_heartbeatTimer[channel])
        _heartbeatTimer[channel] = null
      }
      _pongMissed[channel] = 0
      _scheduleReconnect(channel)
    }

    ws.onerror = (e) => {
      // eslint-disable-next-line no-console
      console.warn(`[WS] ${channel} error`, e)
    }

    ws.onmessage = (e) => {
      let payload
      try {
        payload = JSON.parse(e.data)
      } catch (err) {
        // eslint-disable-next-line no-console
        console.warn('[WS] bad payload', e.data, err)
        return
      }
      // v10 增: ping/pong 双向心跳 (M-005)
      //   服务端 30s 发 ping → 客户端立即回 pong (重置服务端 timeout)
      //   客户端 30s 发 ping → 服务端回 pong (重置 _pongMissed 计数)
      const t = payload?.type
      if (t === 'ping') {
        try { ws.send(JSON.stringify({ type: 'pong', ts: payload.ts })) } catch (_) { /* socket 已关 */ }
        return
      }
      if (t === 'pong') {
        _pongMissed[channel] = 0
        return
      }
      // eslint-disable-next-line no-console
      console.log(`[WS][${channel}]`, payload)
      lastEvent.value = payload
      // 业务分发由注入的回调处理（解耦 connection / dispatch）
      onMessage(payload)
    }
  }

  function _scheduleReconnect(channel) {
    if (_reconnectTimer[channel]) return
    const c = _retryCount[channel] || 1
    const delay = Math.min(RECONNECT_BASE_DELAY * 2 ** (c - 1), RECONNECT_MAX_DELAY)
    _reconnectTimer[channel] = setTimeout(() => {
      _reconnectTimer[channel] = null
      _openChannel(channel)
    }, delay)
  }

  function connect() {
    for (const ch of CHANNELS) _openChannel(ch)
  }

  function disconnect() {
    for (const ch of CHANNELS) {
      if (_reconnectTimer[ch]) {
        clearTimeout(_reconnectTimer[ch])
        _reconnectTimer[ch] = null
      }
      if (_heartbeatTimer[ch]) {  // v10 增
        clearInterval(_heartbeatTimer[ch])
        _heartbeatTimer[ch] = null
      }
      _retryCount[ch] = 0  // v7 增: 主动断开也清计数
      _pongMissed[ch] = 0  // v10 增
      if (_sockets[ch]) {
        _sockets[ch].onclose = null
        _sockets[ch].close()
        _sockets[ch] = null
      }
    }
    connected.value = false
  }

  return { connect, disconnect, connected, lastEvent }
}
