import { defineStore } from 'pinia'
import { ref } from 'vue'
import { ElNotification } from 'element-plus'
// v8: 删 useOrderStore - orderStore 不再持有 orders/trades, 单一缓存源在 holdings
// import { useOrderStore } from './order'  // 移除
import { usePositionStore } from './position'
import { useAssetStore } from './asset'
import { useQuoteStore } from './quote'
import { useHoldingsStore } from './holdings'
import { STATUS_LABEL } from '../utils/format'

const CHANNELS = ['order_update', 'trade_update', 'position_update', 'asset_update', 'quote_update']
// v7 改: WS 重连从固定 3s 改为指数退避
//   delay = min(1000 * 2^retryCount, 30000)
//   broker 长时间故障时不会 3s 一次疯狂重连
const RECONNECT_BASE_DELAY = 1000
const RECONNECT_MAX_DELAY = 30000
// 行情直连 hqserver :8765，不再走 server 后端转发
const QUOTE_WS_HOST = (() => {
  // 优先用环境变量；否则复用当前 host（hqserver 通常跟前端同机部署）
  if (typeof import.meta !== 'undefined' && import.meta.env?.VITE_QUOTE_WS_URL) {
    return import.meta.env.VITE_QUOTE_WS_URL.replace(/^ws/, '')
  }
  return window.location.hostname + ':8765'
})()

/**
 * WS 推送订阅
 *
 * 协议：服务端把柜台 push 包（func + rows）原样转成 JSON：
 *   { type: "ord_cfm" | "trd_cfm" | "pos_cfm" | "ast_cfm",
 *     channel: "order_update" | "trade_update" | ...,
 *     ts: "...", data: { ...row fields... } }
 *
 * 行为：
 *   - 启动时连接所有 4 个 channel
 *   - 收到消息按 type 分发到 order / position / asset store
 *   - Element Plus 通知（成功/警告/危险，对应已成/部成/废单）
 *   - 断线自动重连
 */
export const useWsStore = defineStore('ws', () => {
  const connected = ref(false)
  const lastEvent = ref(null)
  const _sockets = {}    // channel -> WebSocket
  const _reconnectTimer = {}
  const _retryCount = {}  // v7 增: 指数退避计数, per-channel
  const _heartbeatTimer = {}  // v10 增: 客户端主动 ping 定时器, per-channel
  const _pongMissed = {}      // v10 增: 累计未回 pong 次数, per-channel

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
      _dispatch(payload)
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

  // ---- 业务分发 --------------------------------------------------------

  function _dispatch(payload) {
    const t = payload?.type
    if (t === 'ord_cfm') _onOrderCfm(payload.data)
    else if (t === 'trd_cfm') _onTradeCfm(payload.data)
    else if (t === 'pos_cfm') _onPositionCfm(payload.data)
    else if (t === 'ast_cfm') _onAssetCfm(payload.data)
    else if (t === 'quote') _onQuote(payload.data)
  }

  function _onQuote(row) {
    // row: { stock_code, last_price, fields, body, ts? }
    if (!row || !row.stock_code) return
    // 直接写入 quote store（hqserver 推所有 *.SH / *.SZ，无需白名单）
    // 下单页输入任意标的即可显示行情
    const quoteStore = useQuoteStore()
    quoteStore.update({
      stock_code: row.stock_code,
      last_price: row.last_price,
      fields: row.fields,
      body: row.body,
      ts: row.ts || Date.now()
    })
    // 同步给 holdings store（用于持仓代码的实时市值计算）
    try {
      const holdings = useHoldingsStore()
      holdings.applyQuote(row)
    } catch (_) { /* 同上 */ }
  }

  function _onOrderCfm(row) {
    // v8: 单一缓存源 - 只走 holdings.applyOrderPush
    //   - 匹配键 = order_no（本地 PK），broker 推的 row.order_no 由后端注入（OrderOut 字段）
    //   - 兜底: row.remark ≡ order_no（broker 透传）
    //   - 后端 push 链路已注入 trd_date = activeTrdDate（权威）, 前端守门在 holdings 内部
    //   - 防御性 status 重算 holdings 内部完成
    const orderNo = row.order_no || row.remark || ''
    if (!orderNo) {
      console.warn('[ws._onOrderCfm] 缺 order_no/remark, 跳过:', row)
      return
    }
    const status = row.status || row.order_status || ''
    const code = row.stock_code || ''
    const mapped = _mapOrderStatus(status)

    // 构造完整 row（兜底 remark, status_msg; 调一次 holdings.applyOrderPush 单点入口）
    const enriched = {
      ...row,
      order_no: orderNo,
      // v8: 兜底 status 字符串（holdings.applyOrderPush 会再用 inferOrderStatus 重算）
      status: mapped || status || row.status || ''
    }

    try {
      const holdings = useHoldingsStore()
      holdings.applyOrderPush(enriched, 'update')
    } catch (e) {
      console.error('[ws._onOrderCfm] applyOrderPush failed:', e)
    }

    _notifyOrder(code, mapped || status, enriched)
  }

  function _onTradeCfm(row) {
    // v8: 单一缓存源 - 只走 holdings.applyTradePush
    //   - 匹配键 = trade_id（broker 推 traded_id 兼容 trade_id）
    //   - trd_date 由后端 push 链路注入 = activeTrdDate
    //   - order_no: 兜底 row.remark（broker 透传）
    const tradeId = row.traded_id || row.trade_id || ''
    if (!tradeId) {
      console.warn('[ws._onTradeCfm] 缺 trade_id/traded_id, 跳过:', row)
      return
    }
    const enriched = {
      ...row,
      trade_id: tradeId,
      order_no: row.order_no || row.remark || ''
    }

    try {
      const holdings = useHoldingsStore()
      holdings.applyTradePush(enriched)
    } catch (e) {
      console.error('[ws._onTradeCfm] applyTradePush failed:', e)
    }

    ElNotification({
      title: '成交通知',
      message: `${row.stock_code || ''} 成交 ${row.volume || 0}@${row.price || 0}`,
      type: 'success',
      duration: 4000
    })
  }

  function _onPositionCfm(row) {
    const positionStore = usePositionStore()
    const code = row.stock_code || ''
    const idx = positionStore.positions.findIndex((p) => p.stock_code === code)
    if (idx >= 0) {
      positionStore.positions[idx] = {
        ...positionStore.positions[idx],
        ...row
      }
    } else if (code) {
      positionStore.positions.unshift(row)
    }
    // 同步到 holdings store（让实时市值计算基于最新持仓量）
    try {
      const holdings = useHoldingsStore()
      holdings.applyPositionPush(row)
    } catch (_) { /* holdings 可能在登出态被销毁 */ }
  }

  function _onAssetCfm(row) {
    // 柜台 push 过来的资产同步到 asset store
    const assetStore = useAssetStore()
    assetStore.asset = {
      cash: Number(row.cash) || 0,
      frozen_cash: Number(row.frozen_cash) || 0,
      market_value: Number(row.market_value) || 0,
      total_asset: Number(row.total_asset) || 0
    }
    // 同步到 holdings store（cachedAsset）
    try {
      const holdings = useHoldingsStore()
      holdings.applyAssetPush(row)
    } catch (_) { /* 同上 */ }
  }

  function _notifyOrder(code, status, row) {
    // 柜台数字：48 未报 / 49 待报 / 50 已报 / 51 已报待撤 / 52 部成待撤
    //           53 部撤 / 54 已撤 / 55 部成 / 56 已成 / 57 废单 / 255 未知
    const s = String(status || '')
    const label = STATUS_LABEL[s] || s || '已报'
    const filled = Number(row.traded_volume) || 0
    const volume = Number(row.volume) || 0
    let nType = 'info'
    let msg = `${code} 状态：${label}`
    if (s === '56') { nType = 'success'; msg = `${code} 已成交 ${volume}@${row.price || ''}` }
    else if (s === '55' || s === '52') { nType = 'warning'; msg = `${code} 部成 ${filled}/${volume}` }
    else if (s === '57') { nType = 'error'; msg = `${code} 废单${row.status_msg ? '：' + row.status_msg : ''}` }
    else if (s === '54' || s === '53') { nType = 'info'; msg = `${code} 已撤单` }

    ElNotification({ title: '委托更新', message: msg, type: nType, duration: 3500 })
  }

  return {
    connected,
    lastEvent,
    connect,
    disconnect
  }
})

// ---- 工具 --------------------------------------------------------------

function _mapOrderStatus(raw) {
  if (!raw) return ''
  const s = String(raw).trim()
  if (!s) return ''
  // 已经是柜台数字（48-57 / 255）或已知的英文 key，都原样返回
  return s
}

function payload_ts_to_hms() {
  const d = new Date()
  return [d.getHours(), d.getMinutes(), d.getSeconds()]
    .map((n) => String(n).padStart(2, '0'))
    .join(':')
}
