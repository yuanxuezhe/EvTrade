/**
 * ws_dispatch.js — WS payload 业务分发 + Element Plus 通知
 *
 * 职责:
 * - dispatchPayload(payload) — type → store
 * - _onOrderCfm / _onTradeCfm / _onPositionCfm / _onAssetCfm / _onQuote
 * - _notifyOrder — 委托状态变更通知
 *
 * 不持有 WebSocket 连接，纯函数式（依赖注入 store getter）
 * 这样 ws_heartbeat.js 持有连接，dispatch 拿 payload 就行
 */
import { ElNotification } from 'element-plus'
import { usePositionStore } from './position'
import { useAssetStore } from './asset'
import { useQuoteStore } from './quote'
import { useHoldingsStore } from './holdings'
import { STATUS_LABEL } from '../utils/format'

/**
 * payload 入口（ws_heartbeat 的 onmessage 调用）
 * payload = { type, channel, ts, data }
 */
export function dispatchPayload(payload) {
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

// ---- 工具 --------------------------------------------------------------

function _mapOrderStatus(raw) {
  if (!raw) return ''
  const s = String(raw).trim()
  if (!s) return ''
  // 已经是柜台数字（48-57 / 255）或已知的英文 key，都原样返回
  return s
}
