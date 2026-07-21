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
import { makeLogger } from '../utils/logger'

const log = makeLogger('ws')

// change 2026-07-21-system-init-page-refresh: 加 system_update 频道
//   - 后端 init_trading_day 成功后会通过 ws_manager.broadcast('system_update', {...})
//     推送 type=init_completed 事件 (server/api/admin/sys_status.py:118)
//   - 前端 ws_dispatch._onInitCompleted 接收后做：active day 切换 + force bootstrap
//   - 之前 ws_dispatch._onInitCompleted 写了但永远收不到 (CHANNELS 没列)，导致日初后页面不切日
export const CHANNELS = ['order_update', 'trade_update', 'quote_update', 'strategy_update', 'system_update']

// v7 改: WS 重连从固定 3s 改为指数退避
//   delay = min(1000 * 2^retryCount, 30000)
//   broker 长时间故障时不会 3s 一次疯狂重连
export const RECONNECT_BASE_DELAY = 1000
export const RECONNECT_MAX_DELAY = 30000

// change ws-quote-fanout: quote_update 改为走后端 /ws/quote_update，不再直连 hqserver :8765
//   - 原因：hqserver 是裸 ws，不支持 wss；公网访问必然 TLS 失败
//   - 数据来源：后端 quote_consumer 已通过 ws_manager.broadcast('quote_update', ...) fanout
//   - 保留 VITE_QUOTE_WS_URL 兼容：若设置成同源 URL（含 token query），仍可被旧代码消费
const QUOTE_WS_HOST = (() => {
  if (typeof import.meta !== 'undefined' && import.meta.env?.VITE_QUOTE_WS_URL) {
    return import.meta.env.VITE_QUOTE_WS_URL.replace(/^ws/, '')
  }
  // 默认同源走后端：'localhost' 或 'evtrade.ngx.evdata.top'
  return window.location.host
})()

function _wsUrl(channel) {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  // 所有 channel 一律走后端 /ws/{channel}?token=JWT
  //   - 后端 endpoint 已注册到 /ws/{channel}，heartbeat sender 对 quote_update 特判跳过服务端 ping
  //   - quote_update 的实时数据靠 quote_consumer 的 ws_manager.broadcast 提供
  const token = localStorage.getItem('evtrade-token') || ''
  const sep = token ? '?' : ''  // 第一个 query 参数用 ?，不是 &
  // quote_update: 如果 VITE_QUOTE_WS_URL 是自定义的（局域网直连 hqserver），则不加 token
  if (channel === 'quote_update' && typeof import.meta !== 'undefined' && import.meta.env?.VITE_QUOTE_WS_URL) {
    return `${proto}://${QUOTE_WS_HOST}/`
  }
  return `${proto}://${window.location.host}/ws/${channel}${sep}token=${encodeURIComponent(token)}`
}

/**
 * 工厂: 创建一个 ws manager 实例
 *
 * @param {Function} onMessage  payload → void（业务分发回调，注入 ws_dispatch.dispatchPayload）
 * @param {Function} [onConnected]  (channel) → void（连接成功回调，用于 2026-07-14 fix 重订阅）
 * @returns {{connect, disconnect, connected, lastEvent, sendToChannel}}
 */
export function createWsManager(onMessage, onConnected) {
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
      log.info(`${channel} connected`)
      // 2026-07-14 fix-ws-reconnect-subscription: 通知业务层连接成功
      //   让 quote store 强制重发 subscribedSet (服务端 disconnect 时已 clear_ws)
      try { onConnected?.(channel) } catch (e) { /* 业务层错误不影响 ws */ }
      // change ws-quote-fanout: 客户端 30s 主动 ping — quote_update 现在走后端，
      //   同样走 ping/pong 心跳。后端 quote_update 通道的 heartbeat sender 已特判跳过服务端 ping，
      //   但客户端主动 ping 后端仍会回 pong（见 server/ws/endpoint.py: ping/pong 双向逻辑）。
      if (!_heartbeatTimer[channel]) {
        _heartbeatTimer[channel] = setInterval(() => {
          if (_sockets[channel]?.readyState === WebSocket.OPEN) {
            try {
              _sockets[channel].send(JSON.stringify({ type: 'ping', ts: Date.now() }))
              _pongMissed[channel] = (_pongMissed[channel] || 0) + 1
              // 连续 3 次 (90s) 没回 pong → 主动断开触发重连
              if (_pongMissed[channel] >= 3) {
                log.warn(`${channel} pong missed ${_pongMissed[channel]}x, force close`)
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
      log.info(`${channel} closed, reconnect in ${delay}ms (attempt #${c})`)
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
      log.warn(`${channel} error`, e)
    }

    ws.onmessage = (e) => {
      let payload
      try {
        payload = JSON.parse(e.data)
      } catch (err) {
        // eslint-disable-next-line no-console
        log.warn('bad payload', e.data, err)
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
      log.debug(`[${channel}]`, payload)
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

  /**
   * 2026-07-09 quote-snapshot-subscribe: 给指定 channel 发业务消息
   *   - 用于 quote_store.subscribe() → 调 ws.send({type:'subscribe', stock_codes:[...]})
   *   - 默认 channel = 'quote_update'
   *   - 静默失败 (socket 未就绪 / 关闭): 返 false
   */
  function sendToChannel(channel, payload) {
    const ws = _sockets[channel]
    if (!ws || ws.readyState !== WebSocket.OPEN) return false
    try {
      ws.send(JSON.stringify(payload))
      return true
    } catch (_) {
      return false
    }
  }

  return { connect, disconnect, connected, lastEvent, sendToChannel }
}
