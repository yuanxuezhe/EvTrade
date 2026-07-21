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
import { useSyncStore } from './sync'  // v21 stock-info-crawler
import { useWsStore } from './ws'
// change 2026-07-15-system-init-broadcast: 收到 init_completed 时需要刷新 asset/position store
import { useAssetStore } from './asset'
import { usePositionStore } from './position'
import { STATUS_LABEL } from '../utils/format'
import { makeLogger } from '../utils/logger'

const log = makeLogger('ws')

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
  // 2026-07-09 quote-snapshot-subscribe
  else if (t === 'subscribe_ack') _onSubscribeAck(payload.data)
  else if (t === 'unsubscribe_ack') _onUnsubscribeAck(payload.data)
  // v21 stock-info-crawler: sync_update 频道 (sync_started/progress/completed/failed/stopped/stock_synced)
  else if (t === 'sync_started') _onSyncStarted(payload.data)
  else if (t === 'sync_progress') _onSyncProgress(payload.data)
  else if (t === 'sync_completed') _onSyncCompleted(payload.data)
  else if (t === 'sync_failed') _onSyncFailed(payload.data)
  else if (t === 'sync_stopped') _onSyncStopped(payload.data)
  else if (t === 'stock_synced') _onStockSynced(payload.data)
  // change 2026-07-15-system-init-broadcast: 日初成功后推 init_completed → 全量刷新缓存
  else if (t === 'init_completed') _onInitCompleted(payload.data)
}

/**
 * 2026-07-09 quote-snapshot-subscribe: 发 subscribe 协议到后端 ws /ws/quote_update
 *   - 走 wsStore.sendToChannel('quote_update', {type:'subscribe', stock_codes:[...]})
 *   - 失败静默 (socket 未就绪, 业务由 REST 兜底)
 *   - 供 quoteStore.subscribe() 调（动态 import）
 */
export function subscribe(codes) {
  if (!Array.isArray(codes) || codes.length === 0) return false
  try {
    const wsStore = useWsStore()
    return wsStore.sendToChannel('quote_update', { type: 'subscribe', stock_codes: codes })
  } catch (e) {
    log.warn('ws subscribe failed:', e?.message)
    return false
  }
}

export function unsubscribe(codes) {
  if (!Array.isArray(codes) || codes.length === 0) return false
  try {
    const wsStore = useWsStore()
    return wsStore.sendToChannel('quote_update', { type: 'unsubscribe', stock_codes: codes })
  } catch (e) {
    log.warn('ws unsubscribe failed:', e?.message)
    return false
  }
}

function _onSubscribeAck(data) {
  if (!data) return
  if (data.code !== 0) {
    log.warn('subscribe_ack 失败:', data.msg, 'codes:', data.stock_codes)
    return
  }
  const quoteStore = useQuoteStore()
  if (data.snapshots && Object.keys(data.snapshots).length > 0) {
    quoteStore.applySnapshots(data.snapshots)
  }
  log.debug('subscribe_ack ok, codes:', data.stock_codes, 'snapshots:', Object.keys(data.snapshots || {}).length)
}

function _onUnsubscribeAck(data) {
  if (!data) return
  log.debug('unsubscribe_ack ok, removed:', data.stock_codes)
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
    log.warn('_onOrderCfm 缺 order_no, 跳过:', row)
    return
  }

  // v13: 拿 applyOrderPush 返回的 final status (merged.status / row.status)
  //   之前用 row.status (broker 原始) 与表格显示 (merged.status 推断) 不一致
  //   守门/跳过返 null, 不发通知
  // v79 (REQ-TRADE-032): 前端不做去重过滤, 后端只推 50/57, 收到即通知
  let finalStatus = null
  try {
    const holdings = useHoldingsStore()
    finalStatus = holdings.applyOrderPush(row, 'update')
  } catch (e) {
    log.error('_onOrderCfm applyOrderPush failed:', e)
  }

  if (finalStatus == null) return

  // v79 (REQ-TRADE-032): 控制台日志 — 委托确认: 交易日、委托编号、证券代码、状态
  log.info(`[ord_cfm] 委托确认: trd_date=${row.trd_date || '-'} order_no=${row.order_no} code=${row.stock_code} status=${finalStatus}`)

  _notifyOrder(row.stock_code, finalStatus, row)
}

function _onTradeCfm(row) {
  // 后端重组包后，row 已是 TradeOut 格式（trade_id/volume/price 等）
  if (!row || !row.trade_id) {
    log.warn('_onTradeCfm 缺 trade_id, 跳过:', row)
    return
  }

  try {
    const holdings = useHoldingsStore()
    holdings.applyTradePush(row)
  } catch (e) {
    log.error('_onTradeCfm applyTradePush failed:', e)
  }

  const dir = String(row.order_type) === '24' ? '卖' : '买'
  // 状态: 累计成交后从订单表取 status (部成/已成), trd_cfm 本身不直接给 status
  //   用 holdings.orders 找原订单取 status_msg 或 status
  let orderStatus = '-'
  let orderStatusLabel = '-'
  try {
    const holdings = useHoldingsStore()
    const ord = (holdings.orders || []).find((o) => o.order_no === row.order_no)
    if (ord) {
      orderStatus = ord.status || '-'
      orderStatusLabel = STATUS_LABEL[orderStatus] || orderStatus
    }
  } catch (_) { /* 取不到状态兜底 */ }

  // v79 (REQ-TRADE-032): 控制台日志 — 成交推送: 交易日、委托编号、证券代码、成交数量@成交价格、状态
  log.info(`[trd_cfm] 成交推送: trd_date=${row.trd_date || '-'} order_no=${row.order_no} code=${row.stock_code} ${row.volume}@${row.price} status=${orderStatusLabel}`)

  ElNotification({
    title: '成交通知',
    message: `${row.trd_date || '-'} ${row.order_no} ${row.stock_code} ${row.volume}@${row.price} ${orderStatusLabel}`,
    type: 'success',
    duration: 4000
  })
}

function _notifyOrder(code, status, row) {
  // v79 (REQ-TRADE-032): 文案统一 — 交易日、委托编号、证券代码、状态
  //   后端 ord_cfm 只推 50 (已报) / 57 (废单), 前端不做 4 类状态判断
  //   之前 line 210-215 的 56/55/52/57/54/53/50/49 分支全部不再触发
  const s = String(status || '')
  const label = STATUS_LABEL[s] || s || '已报'
  const trdDate = row.trd_date || '-'
  const orderNo = row.order_no || '-'
  let nType = 'info'
  let msg = `${trdDate} ${orderNo} ${code} ${label}`

  ElNotification({ title: '委托确认', message: msg, type: nType, duration: 3500 })
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
    log.warn('_onStrategyUpdate 缺 strategy_id, 跳过:', row)
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
    log.error('_onStrategyUpdate failed:', e)
  }
}

function _todayYYYYMMDD() {
  const d = new Date()
  return `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, '0')}${String(d.getDate()).padStart(2, '0')}`
}

// ============================================================
// v21 stock-info-crawler: sync_update 频道路由（仅路由到 sync store，不抛异常）
// 后端 sync manager 推送: sync_started / sync_progress / sync_completed
//                       / sync_failed / sync_stopped / stock_synced
// ============================================================

function _onSyncStarted(data) {
  if (!data) return
  try { useSyncStore().onSyncStarted(data) }
  catch (e) { log.warn('_onSyncStarted:', e?.message) }
}
function _onSyncProgress(data) {
  if (!data) return
  try { useSyncStore().onSyncProgress(data) }
  catch (e) { log.warn('_onSyncProgress:', e?.message) }
}
function _onSyncCompleted(data) {
  if (!data) return
  try { useSyncStore().onSyncCompleted(data) }
  catch (e) { log.warn('_onSyncCompleted:', e?.message) }
}
function _onSyncFailed(data) {
  if (!data) return
  try { useSyncStore().onSyncFailed(data) }
  catch (e) { log.warn('_onSyncFailed:', e?.message) }
}
function _onSyncStopped(data) {
  if (!data) return
  try { useSyncStore().onSyncStopped(data) }
  catch (e) { log.warn('_onSyncStopped:', e?.message) }
}
function _onStockSynced(data) {
  if (!data) return
  try { useSyncStore().onStockSynced(data) }
  catch (e) { log.warn('_onStockSynced:', e?.message) }
}

// ============================================================
// change 2026-07-21-system-init-page-refresh: 收到后端 init_completed
//   1) 切交易日 + force re-bootstrap (重置 activeTrdDate, 清 IDB, 拉新日 RPC 4 路)
//   2) 通知 SystemInit.vue 当前交易日卡片刷新 (window CustomEvent 解耦, 避免循环依赖)
//   3) 不弹 toast / Notification, 静默更新 (用户期望与点刷新按钮同体验)
//   4) ws 推失败时由 SystemInit.vue handleInit 同步刷新路径兜底
//   change 2026-07-15-system-init-broadcast: 此函数原本只 refreshAll 缓存, 不切日
//   change 2026-07-21-system-init-page-refresh: 升级为 force re-bootstrap (holdings.resetForNewDay)
// ============================================================
function _onInitCompleted(data) {
  if (!data) return
  log.info('init_completed 收到:', data.trd_date, 'status=', data.status, 'report_id=', data.report_id)
  // 1) 切交易日 + 重置缓存 + 重拉 RPC (主路径)
  //   - bootstrap 内部会调 _resolveActiveDay 拉新 activeTrdDate
  //   - WS 推送守门、Position.vue netChange、T0Trade 当前日判断全部跟随新日
  try {
    const hs = useHoldingsStore()
    if (typeof hs.resetForNewDay === 'function') {
      hs.resetForNewDay()
    } else {
      // 兜底: 旧版本 store 暴露没 resetForNewDay, 降级 refreshAll
      log.warn('holdings.resetForNewDay 缺失, 降级 refreshAll')
      hs.refreshAll()
      useAssetStore().fetchAsset()
      usePositionStore().fetchPositions()
    }
  } catch (e) {
    log.warn('_onInitCompleted resetForNewDay failed:', e?.message)
  }
  // 2) 通知 SystemInit.vue 当前交易日卡片刷新 (loadCurrent 重新拉 /api/system/active)
  //   - 用 CustomEvent 而非直接 import SystemInit: 解耦 + 避免 ws_dispatch 反向依赖 view
  //   - SystemInit.vue onMounted 时 addEventListener, onUnmounted removeEventListener
  try {
    if (typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent('evtrade:day-init-completed', {
        detail: { trd_date: data.trd_date, status: data.status, report_id: data.report_id }
      }))
    }
  } catch (e) {
    log.warn('_onInitCompleted dispatchEvent failed:', e?.message)
  }
}

/**
 * 订阅 sync_update WS 频道（前端 /admin/sync 页面 mount 时调用）
 * 返回一个 unsubscribe 函数（页面 unmount 时调用）
 *
 * 注：sync_update 不需要 client 主动 subscribe 协议——只要连上 /ws/sync_update 就推
 *     所以这里只是包装一层，方便组件 onBeforeUnmount 调用
 */
export function subscribeSync() {
  // 目前 sync_update 是 server-push（无 ack 协议），直接标记已连接
  // 未来若加 client-filter 再扩展 sendToChannel 调用
  return () => {
    try { useSyncStore().setWsConnected(false) }
    catch { /* store 已销毁 */ }
  }
}
