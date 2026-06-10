import { defineStore } from 'pinia'
import { ref } from 'vue'
import { ElNotification } from 'element-plus'
import { useOrderStore } from './order'
import { usePositionStore } from './position'
import { useAssetStore } from './asset'
import { STATUS_LABEL } from '../utils/format'

const CHANNELS = ['order_update', 'trade_update', 'position_update', 'asset_update']
const RECONNECT_DELAY = 3000

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

  function _wsUrl(channel) {
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    return `${proto}://${window.location.host}/ws/${channel}`
  }

  function _openChannel(channel) {
    if (_sockets[channel] && _sockets[channel].readyState === WebSocket.OPEN) {
      return
    }
    const ws = new WebSocket(_wsUrl(channel))
    _sockets[channel] = ws

    ws.onopen = () => {
      connected.value = true
      // eslint-disable-next-line no-console
      console.log(`[WS] ${channel} connected`)
    }

    ws.onclose = () => {
      // eslint-disable-next-line no-console
      console.log(`[WS] ${channel} closed, reconnect in ${RECONNECT_DELAY}ms`)
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
      lastEvent.value = payload
      _dispatch(payload)
    }
  }

  function _scheduleReconnect(channel) {
    if (_reconnectTimer[channel]) return
    _reconnectTimer[channel] = setTimeout(() => {
      _reconnectTimer[channel] = null
      _openChannel(channel)
    }, RECONNECT_DELAY)
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
  }

  function _onOrderCfm(row) {
    const orderStore = useOrderStore()
    const orderId = row.order_id || row.order_sysid || ''
    const status = row.status || row.order_status || ''
    const code = row.stock_code || ''
    const mapped = _mapOrderStatus(status)

    const existing = orderStore.orders.find(
      (o) => o.order_id === orderId || o.order_sysid === orderId
    )
    if (existing) {
      if (mapped) existing.status = mapped
      const tv = Number(row.traded_volume)
      if (!Number.isNaN(tv)) existing.traded_volume = tv
      const tp = Number(row.traded_price)
      if (!Number.isNaN(tp)) existing.traded_price = tp
    } else if (orderId) {
      orderStore.orders.unshift({
        order_id: orderId,
        stock_code: code,
        direction: row.direction || 'BUY',
        volume: Number(row.volume || row.order_volume) || 0,
        price: Number(row.price) || 0,
        price_type: row.price_type || 'LIMIT',
        status: mapped || status || 'reported',
        traded_volume: Number(row.traded_volume) || 0,
        traded_price: Number(row.traded_price) || 0,
        order_time: row.order_time || payload_ts_to_hms()
      })
    }

    _notifyOrder(code, mapped || status, row)
  }

  function _onTradeCfm(row) {
    const orderStore = useOrderStore()
    orderStore.trades.unshift({
      trade_id: row.trade_id || '',
      order_id: row.order_id || '',
      stock_code: row.stock_code || '',
      direction: row.direction || '',
      volume: Number(row.volume) || 0,
      price: Number(row.price) || 0,
      trade_time: row.trade_time || payload_ts_to_hms()
    })

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
  }

  function _onAssetCfm(row) {
    const assetStore = useAssetStore()
    assetStore.asset = {
      cash: Number(row.cash) || 0,
      frozen_cash: Number(row.frozen_cash) || 0,
      market_value: Number(row.market_value) || 0,
      total_asset: Number(row.total_asset) || 0
    }
  }

  function _notifyOrder(code, status, row) {
    const label = STATUS_LABEL[status] || status || '已报'
    const filled = Number(row.traded_volume) || 0
    const volume = Number(row.volume) || 0
    let nType = 'info'
    let msg = `${code} 状态：${label}`
    if (status === 'filled') { nType = 'success'; msg = `${code} 已成交 ${volume}@${row.price || ''}` }
    else if (status === 'partial' || status === 'partial_pending_cancel') { nType = 'warning'; msg = `${code} 部成 ${filled}/${volume}` }
    else if (status === 'rejected') { nType = 'error'; msg = `${code} 废单${row.status_msg ? '：' + row.status_msg : ''}` }
    else if (status === 'cancelled' || status === 'partial_cancelled') { nType = 'info'; msg = `${code} 已撤单` }

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
  // 已经是前端 key（unreported / reported / filled ...）
  if (STATUS_LABEL[raw]) return raw
  // XtQuant 字符串数字
  const m = {
    '48': 'unreported',
    '49': 'pending_report',
    '50': 'reported',
    '51': 'reported_cancel',
    '52': 'partial_pending_cancel',
    '53': 'partial_cancelled',
    '54': 'cancelled',
    '55': 'partial',
    '56': 'filled',
    '57': 'rejected',
    '255': 'unknown',
    'pending': 'pending'
  }
  return m[String(raw)] || ''
}

function payload_ts_to_hms() {
  const d = new Date()
  return [d.getHours(), d.getMinutes(), d.getSeconds()]
    .map((n) => String(n).padStart(2, '0'))
    .join(':')
}
