import { defineStore } from 'pinia'
import { ref } from 'vue'
import { ElNotification } from 'element-plus'
import { useOrderStore } from './order'
import { usePositionStore } from './position'
import { useAssetStore } from './asset'
import { useQuoteStore } from './quote'
import { useHoldingsStore } from './holdings'
import { STATUS_LABEL } from '../utils/format'

const CHANNELS = ['order_update', 'trade_update', 'position_update', 'asset_update', 'quote_update']
const RECONNECT_DELAY = 3000
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
      // eslint-disable-next-line no-console
      console.log(`[WS][${channel}]`, payload)
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
      // v5 schema: 柜台透传字段名是 remark (= 本地 order_no)
      if (row.remark) existing.remark = String(row.remark)
      if (row.status_msg) existing.status_msg = String(row.status_msg)
    } else if (orderId) {
      orderStore.orders.unshift({
        order_id: orderId,
        stock_code: code,
        // 柜台 order_type 数字串：股票 23=买入，24=卖出
        order_type: row.order_type || '23',
        volume: Number(row.volume || row.order_volume) || 0,
        price: Number(row.price) || 0,
        // 柜台 price_type 数字：5=最新价 11=指定价 14=对手价 44=市价
        price_type: row.price_type != null ? Number(row.price_type) : 11,
        status: mapped || status || 'reported',
        traded_volume: Number(row.traded_volume) || 0,
        traded_price: Number(row.traded_price) || 0,
        order_time: row.order_time || payload_ts_to_hms(),
        remark: row.remark ? String(row.remark) : '',
        status_msg: row.status_msg ? String(row.status_msg) : ''
      })
    }

    // 同步到 holdings store 缓存（操作记录 + 数据保持一致）
    try {
      const holdings = useHoldingsStore()
      holdings.applyOrderPush(row, existing ? 'update' : 'open')
    } catch (_) { /* 同上 */ }

    _notifyOrder(code, mapped || status, row)
  }

  function _onTradeCfm(row) {
    const orderStore = useOrderStore()
    orderStore.trades.unshift({
      // 柜台报文字段名是 traded_id / traded_time；保留 trade_id / trade_time 作兼容
      trade_id: row.traded_id || row.trade_id || '',
      order_id: row.order_id || '',
      stock_code: row.stock_code || '',
      // 柜台 order_type 数字串：股票 23=买入，24=卖出
      order_type: row.order_type || '',
      volume: Number(row.volume) || 0,
      price: Number(row.price) || 0,
      trade_time: row.traded_time || row.trade_time || payload_ts_to_hms()
    })

    // 同步到 holdings 缓存（操作记录 + 视图立刻反映）
    try {
      const holdings = useHoldingsStore()
      holdings.applyTradePush({
        trade_id: row.traded_id || row.trade_id || '',
        order_id: row.order_id || '',
        stock_code: row.stock_code || '',
        order_type: row.order_type || '',
        volume: Number(row.volume) || 0,
        price: Number(row.price) || 0,
        trade_time: row.traded_time || row.trade_time || payload_ts_to_hms()
      })
    } catch (_) { /* 同上 */ }

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
