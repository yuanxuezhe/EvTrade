/**
 * ws_dispatch.js — WS payload 业务分发 + Element Plus 通知
 *
 * 职责:
 * - dispatchPayload(payload) — type → store
 * - _onOrderCfm / _onTradeCfm / _onQuote
 * - _notifyOrder — 委托状态变更通知
 *
 * 不持有 WebSocket 连接，纯函数式（依赖注入 store getter）
 * 这样 ws_heartbeat.js 持有连接，dispatch 拿 payload 就行
 *
 * v8: 唯一权威源是 holdings store。ws 推送**单一写**到 holdings，
 *     position.js / asset.js 通过 computed 桥接 holdings（不再双写）
 *
 * change consolidate-position-data-flow:
 *   _onPositionCfm / _onAssetCfm 已删除 (xtquant broker 不发 pos_cfm / ast_cfm)
 *   position.js / asset.js 通过 computed 桥接 holdings.positions / cachedAsset
 */
import { ElNotification } from 'element-plus'
import { useQuoteStore } from './quote'
import { useHoldingsStore } from './holdings'
import { useStrategyStore } from './strategy'
import { STATUS_LABEL } from '../utils/format'

/**
 * payload 入口（ws_heartbeat 的 onmessage 调用）
 * payload = { type, channel, ts, data }
 */
export function dispatchPayload(payload) {
  const t = payload?.type
  if (t === 'ord_cfm') _onOrderCfm(payload.data)
  else if (t === 'trd_cfm') _onTradeCfm(payload.data)
  else if (t === 'quote') _onQuote(payload.data)
  else if (t === 'strategy_update') _onStrategyUpdate(payload.data)
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
  // 后端重组包后，row 已是 OrderOut 格式（order_no/status/stock_code 等）
  if (!row || !row.order_no) {
    console.warn('[ws._onOrderCfm] 缺 order_no, 跳过:', row)
    return
  }

  // v13: 拿 applyOrderPush 返回的 final status (merged.status / row.status)
  //   之前用 row.status (broker 原始) 与表格显示 (merged.status 推断) 不一致
  //   守门/跳过返 null, 不发通知
  let finalStatus = null
  try {
    const holdings = useHoldingsStore()
    finalStatus = holdings.applyOrderPush(row, 'update')
  } catch (e) {
    console.error('[ws._onOrderCfm] applyOrderPush failed:', e)
  }

  if (finalStatus != null) {
    _notifyOrder(row.stock_code, finalStatus, row)
  }
}

function _onTradeCfm(row) {
  // 后端重组包后，row 已是 TradeOut 格式（trade_id/volume/price 等）
  if (!row || !row.trade_id) {
    console.warn('[ws._onTradeCfm] 缺 trade_id, 跳过:', row)
    return
  }

  try {
    const holdings = useHoldingsStore()
    holdings.applyTradePush(row)
  } catch (e) {
    console.error('[ws._onTradeCfm] applyTradePush failed:', e)
  }

  const dir = String(row.order_type) === '24' ? '卖' : '买'
  ElNotification({
    title: '成交通知',
    message: `${row.stock_code} ${dir} ${row.volume}@${row.price}`,
    type: 'success',
    duration: 4000
  })
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
  else if (s === '50') { nType = 'warning'; msg = `${code} 部成 ${filled}/${volume}` }
  else if (s === '49') { nType = 'info'; msg = `${code} 已报` }

  ElNotification({ title: '委托更新', message: msg, type: nType, duration: 3500 })
}

/**
 * change strategy_trade task 12: strategy_update 频道分发
 * 后端 engine._broadcast() 推送:
 *   - event: 'regime_changed' / 'grid_triggered' / 'regime_cooldown'
 *   - data: { strategy_id, event, regime_id?, flags_active?, current_price?, action?, order_no?, reject_reason?, ts }
 * 这里把每条事件作为单条 audit 推入 store.appendAudit
 */
function _onStrategyUpdate(row) {
  if (!row || row.strategy_id == null) {
    console.warn('[ws._onStrategyUpdate] 缺 strategy_id, 跳过:', row)
    return
  }
  try {
    const store = useStrategyStore()
    const trdDate = String(row.trd_date || _todayYYYYMMDD())
    const audit = {
      id: row.audit_id ?? `push-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`,
      strategy_id: row.strategy_id,
      regime_id: row.regime_id ?? null,
      trd_date: trdDate,
      trigger_type: row.event || 'grid_triggered',
      flags_active: row.flags_active || [],
      current_price: row.current_price ?? null,
      position_vol: row.position_vol ?? null,
      base_volume: row.base_volume ?? null,
      action_payload: row.action || null,
      order_no: row.order_no || null,
      reject_reason: row.reject_reason || null,
      created_at: row.ts || new Date().toISOString(),
    }
    store.appendAudit(row.strategy_id, trdDate, audit)
  } catch (e) {
    console.error('[ws._onStrategyUpdate] failed:', e)
  }
}

function _todayYYYYMMDD() {
  const d = new Date()
  return `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, '0')}${String(d.getDate()).padStart(2, '0')}`
}
