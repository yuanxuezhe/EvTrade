/**
 * ws_heartbeat.js — WebSocket 连接 / 重连 / 心跳管理（v119 单向心跳）
 *
 * 职责:
 * - WS URL 构造 (含 hqserver 直连 quote_update 特例)
 * - 多个 channel 的 _openChannel / _scheduleReconnect
 * - 客户端 30s 主动 ping, 服务端收到立即回 pong（重置服务端 last_recv）
 * - 客户端 90s 真实空闲超时主动 close 触发重连（避免网络真断时死等）
 * - 服务端 10 分钟无任意消息 → close 4001 "idle timeout" → onclose 接 4001 → 跳登录
 * - 指数退避: delay = min(1000 * 2^retryCount, 30000)
 *
 * v95: 新增 position_update 频道 — 后端 trd_cfm 完成后主动推该标的完整持仓行,
 *      前端 applyPositionUpdate 按 stock_code 整条 ref 替换 (不增量/不 spread).
 *      (change consolidate-position-data-flow 当年删了 pos_cfm/ast_cfm channel,
 *       现在 v95 重新引入 - 但只是 position_update, 没有 asset_update)
 * v119 (2026-08-09): 服务端不再主动 ping, 改为客户端 30s 主动 ping + 服务端 10 分钟 idle 独立计时
 *                    - 删除 _pongMissed 计数器（时钟漂移导致 90s 一次误断）
 *                    - 新增 _lastRecvAt 时间戳，按真实空闲时间判断超时
 *                    - onclose 接 event, code===4001 → 调 _onTokenExpired 跳登录（不重连）
 *                    - _onTokenExpired 走 auth.clear() + router.replace('/login')（避免硬刷新）
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
// v118: 加 'position_update' channel — broker 推 pos_push 事件 → 后端 handle_pos_push 覆盖本地 → ws 推前端
export const CHANNELS = ['order_update', 'trade_update', 'position_update', 'quote_update', 'system_update', 'task_progress_update']
//                                                                            ^^^^^^^^^^^^^^^^
//                                                                            v99: 日初完成后推 init_completed
//                                                                            v95: trd_cfm payload.data.position 同时携带持仓行, 前端 _onTradeCfm 内部处理
//                                                                            v118: pos_push 独立走 position_update channel (broker 持仓变化推送)
//                                                                                  _onTradeCfm.position 不再处理 (trd_cfm 不动持仓)
//                                                                                  (不需要独立 position_update channel, position 行嵌入 trd_cfm payload)

// v7 改: WS 重连从固定 3s 改为指数退避
//   delay = min(1000 * 2^retryCount, 30000)
//   broker 长时间故障时不会 3s 一次疯狂重连
export const RECONNECT_BASE_DELAY = 1000
export const RECONNECT_MAX_DELAY = 30000

// v122: 客户端视角的 WS 空闲超时
//   原 90_000 (3 × 30s ping) 太激进: 服务端 / 反代偶尔吞 pong 时会误断刷屏
//   改 300_000 (5 min), 给服务端/反代留 buffer; 服务端 WS_IDLE_TIMEOUT (600s) 是兜底
//   适用场景: 网络真断但服务端探测不到 (前端先断触发指数退避重连)
export const WS_IDLE_TIMEOUT_MS = 300_000

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
  // Token 为空/过期 → 返回 null, connect/onclose 检测到后直接跳转登录
  const token = localStorage.getItem('evtrade-token') || ''
  if (!token) return null
  const sep = '?'
  // quote_update: 如果 VITE_QUOTE_WS_URL 是自定义的（局域网直连 hqserver），则不加 token
  if (channel === 'quote_update' && typeof import.meta !== 'undefined' && import.meta.env?.VITE_QUOTE_WS_URL) {
    return `${proto}://${QUOTE_WS_HOST}/`
  }
  return `${proto}://${window.location.host}/ws/${channel}${sep}token=${encodeURIComponent(token)}`
}

// Token 过期检测：仅执行一次，停止所有重连并跳转登录
// v119: 改为走 auth store + router（避免硬刷新丢业务状态），auth/router import 失败时回退硬跳转
let _loginRedirected = false
function _onTokenExpired() {
  if (_loginRedirected) return
  _loginRedirected = true
  log.info('token expired/empty, redirecting to login')
  try {
    // 动态 import 避免 ws_heartbeat 在 auth store 初始化前被 import 时循环依赖
    import('./auth').then(({ useAuthStore }) => {
      try { useAuthStore().clear() } catch (_) { /* store 未就绪时忽略 */ }
    }).catch(() => {})
  } catch (_) { /* ignore */ }
  try {
    import('../router').then(({ default: router }) => {
      try {
        if (router.currentRoute.value.path !== '/login') {
          router.replace({ path: '/login' })
        }
      } catch (_) {
        window.location.href = '/login'
      }
    }).catch(() => {
      window.location.href = '/login'
    })
  } catch (_) {
    window.location.href = '/login'
  }
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
  const _lastRecvAt = {}      // v119 增: 最后收到任意消息时间戳（Date.now()），per-channel

  function _openChannel(channel) {
    const url = _wsUrl(channel)
    if (!url) {
      _onTokenExpired()
      return
    }
    if (_sockets[channel] && _sockets[channel].readyState === WebSocket.OPEN) {
      return
    }
    const ws = new WebSocket(url)
    _sockets[channel] = ws

    ws.onopen = () => {
      connected.value = true
      _retryCount[channel] = 0  // v7 增: 连接成功重置退避计数
      _lastRecvAt[channel] = Date.now()  // v119 增: 重置空闲计时
      // eslint-disable-next-line no-console
      log.info(`${channel} connected`)
      // 2026-07-14 fix-ws-reconnect-subscription: 通知业务层连接成功
      //   让 quote store 强制重发 subscribedSet (服务端 disconnect 时已 clear_ws)
      try { onConnected?.(channel) } catch (e) { /* 业务层错误不影响 ws */ }
      // v119: 客户端 30s 主动 ping — 服务端只回 pong（重置其 last_recv）
      //   不再累计 _pongMissed；改为基于真实空闲时间判断超时
      if (!_heartbeatTimer[channel]) {
        _heartbeatTimer[channel] = setInterval(() => {
          const sock = _sockets[channel]
          if (!sock || sock.readyState !== WebSocket.OPEN) return
          try {
            sock.send(JSON.stringify({ type: 'ping', ts: Date.now() }))
          } catch (_) { /* 忽略发送失败 */ }
          // 基于真实空闲时间判断（替代 v10 的 _pongMissed 计数器）
          // 服务端 WS_IDLE_TIMEOUT = 600s; 客户端视角 90s 更激进（网络真断兜底）
          const idleMs = Date.now() - (_lastRecvAt[channel] || Date.now())
          if (idleMs > WS_IDLE_TIMEOUT_MS) {
            log.warn(`${channel} no message for ${Math.round(idleMs / 1000)}s, force close`)
            try { sock.close() } catch (_) { /* ignore */ }
          }
        }, 30000)
      }
    }

    ws.onclose = (event) => {
      // v10 增: 清理心跳定时器
      if (_heartbeatTimer[channel]) {
        clearInterval(_heartbeatTimer[channel])
        _heartbeatTimer[channel] = null
      }
      // v119: 服务端 10 分钟 idle 超时关闭 → 前端调 _onTokenExpired 跳登录、不重连
      //   服务端 4001 同时表示 auth 失败 / idle 超时，行为相同：踢登录
      if (event && event.code === 4001) {
        log.warn(`${channel} closed by server (code=4001), token expired or idle timeout`)
        _onTokenExpired()
        return
      }
      // v7 改: 其他关闭原因（网络抖动、服务端重启等）→ 指数退避重连
      const c = (_retryCount[channel] || 0) + 1
      _retryCount[channel] = c
      const delay = Math.min(RECONNECT_BASE_DELAY * 2 ** (c - 1), RECONNECT_MAX_DELAY)
      // eslint-disable-next-line no-console
      log.info(`${channel} closed, reconnect in ${delay}ms (attempt #${c})`)
      _scheduleReconnect(channel)
    }

    ws.onerror = (e) => {
      // eslint-disable-next-line no-console
      log.warn(`${channel} error`, e)
    }

    ws.onmessage = (e) => {
      // v119: 任何消息到达都重置空闲计时（包括 ping/pong/业务消息）
      _lastRecvAt[channel] = Date.now()
      let payload
      try {
        payload = JSON.parse(e.data)
      } catch (err) {
        // eslint-disable-next-line no-console
        log.warn('bad payload', e.data, err)
        return
      }
      // v119: 仅响应服务端 ping → 立即回 pong；不再处理服务端主动 pong（已删）
      //   客户端主动 ping → 服务端回 pong → 这里收到 pong 时仅重置 _lastRecvAt（首行已做）
      const t = payload?.type
      if (t === 'ping') {
        try { ws.send(JSON.stringify({ type: 'pong', ts: payload.ts })) } catch (_) { /* socket 已关 */ }
        return
      }
      if (t === 'pong') {
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
    // Token 已过期，停止重连
    if (!_wsUrl(channel)) {
      _onTokenExpired()
      return
    }
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
      _lastRecvAt[ch] = 0   // v119 增
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
