/**
 * holdings_apply_results.js — 持仓 store 单资源结果应用 helper
 *
 * 把 Promise.allSettled 的结果（{status, value|reason}）应用到 holdings store 的 ref：
 *   - 成功: 写 IDB (bulkSave) → 写 ref + 更新 refCounts + idbSyncStatus + 写日志
 *   - 失败：标记 refCounts='fail' + idbSyncStatus='error' + 写错误日志
 *
 * 两套 helper：
 *   - _applyXxxResult(r, source)        — bootstrap 用，写"加载成功"日志
 *   - _applyXxxRefreshResult(r)         — refreshAll 用，返回 summary 字符串
 *
 * 调用者：holdings_bootstrap.js 内的 createBootstrap 工厂
 *
 * startup-full-cache-pull 语义:
 *   applyOrdersResult / applyTradesResult 不"整 dict 覆盖" — 按主键去重合并
 *     - orders 主键: trd_date + order_no
 *     - trades 主键: trd_date + order_no + trade_id
 *
 * change system-delegation-price-fill-calc:
 *   applyOrdersRefresh/applyOrdersResult   — 调 normalizeOrder 重算 avg_price + status
 *   applyTradesRefresh/applyTradesResult   — map 调 normalizeTrade 重算 amount
 */
import { parseAsset, normalizeOrder, normalizeTrade } from './holdings_helpers'
import { saveTrade, bulkSave, _orderKey, _tradeKey } from './holdings_idb'

/**
 * 异步 yield 一帧，让浏览器渲染 loading 状态后再赋值
 */
function _yield() {
  return new Promise((r) => setTimeout(r, 0))
}

// ---- 按主键去重 merge helper ----

/**
 * 按 (trd_date, order_no) 主键去重合并
 */
function _mergeOrders(existing, incoming) {
    const keyOf = (o) => `${o.trd_date || ''}|${o.order_no || ''}`
    const m = new Map(existing.map((o) => [keyOf(o), o]))
    for (const inc of incoming) {
        const k = keyOf(inc)
        if (m.has(k)) {
            m.set(k, { ...m.get(k), ...inc })
        } else {
            m.set(k, inc)
        }
    }
    return Array.from(m.values())
}

/**
 * 按 (trd_date, order_no, trade_id) 主键去重合并
 */
function _mergeTrades(existing, incoming) {
    const keyOf = (t) => `${t.trd_date || ''}|${t.order_no || ''}|${t.trade_id || ''}`
    const m = new Map(existing.map((t) => [keyOf(t), t]))
    for (const inc of incoming) {
        const k = keyOf(inc)
        if (m.has(k)) {
            m.set(k, { ...m.get(k), ...inc })
        } else {
            m.set(k, inc)
        }
    }
    return Array.from(m.values())
}

export { _mergeOrders, _mergeTrades }

// ---- refreshAll 用：返回 summary 字符串 --------------------------------

export async function applyAssetRefresh(r, refs) {
  if (r.status === 'fulfilled') {
    const a = parseAsset(r.value)
    if (a) refs.cachedAsset.value = a
    refs.refCounts.value.asset = 'ok'
    refs.idbSyncStatus.value.asset = 'ready'
    return `资金 ¥${(a?.total_asset || 0).toLocaleString()}`
  }
  refs.refCounts.value.asset = 'fail'
  refs.idbSyncStatus.value.asset = 'error'
  refs.log('err', '缓存', 'rpc', '资金刷新失败', String(r.reason?.message || r.reason))
  return null
}

export async function applyPositionsRefresh(r, refs) {
  if (r.status === 'fulfilled') {
    const raw = Array.isArray(r.value) ? r.value : []
    // 先写 IDB
    await bulkSave('positions', raw)
    await _yield()
    refs.positions.value = raw
    refs.refCounts.value.positions = 'ok'
    refs.idbSyncStatus.value.positions = 'ready'
    return `持仓 ${refs.positions.value.length} 只`
  }
  refs.refCounts.value.positions = 'fail'
  refs.idbSyncStatus.value.positions = 'error'
  refs.log('err', '缓存', 'rpc', '持仓刷新失败', String(r.reason?.message || r.reason))
  return null
}

export async function applyOrdersRefresh(r, refs) {
  if (r.status === 'fulfilled') {
    const rawOrders = Array.isArray(r.value) ? r.value : []
    const normalized = rawOrders.map(normalizeOrder)
    // 先写 IDB
    await bulkSave('orders', normalized, _orderKey)
    await _yield()
    refs.orders.value = normalized
    refs.refCounts.value.orders = 'ok'
    refs.idbSyncStatus.value.orders = 'ready'
    return `委托 ${refs.orders.value.length} 条`
  }
  refs.refCounts.value.orders = 'fail'
  refs.idbSyncStatus.value.orders = 'error'
  refs.log('err', '缓存', 'rpc', '委托刷新失败', String(r.reason?.message || r.reason))
  return null
}

export async function applyTradesRefresh(r, refs) {
  if (r.status === 'fulfilled') {
    const rawTrades = Array.isArray(r.value) ? r.value : []
    const normalized = rawTrades.map(normalizeTrade)
    // 先写 IDB
    await bulkSave('trades', normalized, _tradeKey)
    await _yield()
    refs.trades.value = normalized
    // 兜底填充 order_type
    fillTradesDirection(refs)
    refs.refCounts.value.trades = 'ok'
    refs.idbSyncStatus.value.trades = 'ready'
    return `成交 ${refs.trades.value.length} 条`
  }
  refs.refCounts.value.trades = 'fail'
  refs.idbSyncStatus.value.trades = 'error'
  refs.log('err', '缓存', 'rpc', '成交刷新失败', String(r.reason?.message || r.reason))
  return null
}

// ---- bootstrap 用：写"加载成功"日志 ----------------------------------

export async function applyAssetResult(r, refs, source) {
  if (r.status === 'fulfilled') {
    const a = parseAsset(r.value)
    if (a) refs.cachedAsset.value = a
    refs.refCounts.value.asset = 'ok'
    refs.idbSyncStatus.value.asset = 'ready'
    refs.log('ok', '缓存', source, `资金加载成功 (¥${(a?.total_asset || 0).toLocaleString()})`)
  } else {
    refs.refCounts.value.asset = 'fail'
    refs.idbSyncStatus.value.asset = 'error'
    refs.log('err', '缓存', 'rpc', '资金加载失败', String(r.reason?.message || r.reason))
  }
}

export async function applyPositionsResult(r, refs, source) {
  if (r.status === 'fulfilled') {
    const raw = Array.isArray(r.value) ? r.value
      : (Array.isArray(r.value?.list) ? r.value.list : [])
    // 先写 IDB
    await bulkSave('positions', raw)
    await _yield()
    refs.positions.value = raw
    refs.refCounts.value.positions = 'ok'
    refs.idbSyncStatus.value.positions = 'ready'
    refs.log('ok', '缓存', source, `持仓加载成功 (${refs.positions.value.length} 只)`)
  } else {
    refs.refCounts.value.positions = 'fail'
    refs.idbSyncStatus.value.positions = 'error'
    refs.log('err', '缓存', 'rpc', '持仓加载失败', String(r.reason?.message || r.reason))
  }
}

export async function applyOrdersResult(r, refs, source) {
  if (r.status === 'fulfilled') {
    const rawOrders = Array.isArray(r.value) ? r.value
      : (Array.isArray(r.value?.list) ? r.value.list : [])
    const normalized = rawOrders.map(normalizeOrder)
    const merged = _mergeOrders(refs.orders.value || [], normalized)
    // 先写 IDB
    await bulkSave('orders', merged, _orderKey)
    await _yield()
    refs.orders.value = merged
    refs.refCounts.value.orders = 'ok'
    refs.idbSyncStatus.value.orders = 'ready'
    refs.log('ok', '缓存', source, `委托加载成功 (${refs.orders.value.length} 条)`)
  } else {
    refs.refCounts.value.orders = 'fail'
    refs.idbSyncStatus.value.orders = 'error'
    refs.log('err', '缓存', 'rpc', '委托加载失败', String(r.reason?.message || r.reason))
  }
}

export async function applyTradesResult(r, refs, source) {
  if (r.status === 'fulfilled') {
    const rawTrades = Array.isArray(r.value) ? r.value
      : (Array.isArray(r.value?.list) ? r.value.list : [])
    const normalized = rawTrades.map(normalizeTrade)
    const merged = _mergeTrades(refs.trades.value || [], normalized)
    // 先写 IDB
    await bulkSave('trades', merged, _tradeKey)
    await _yield()
    refs.trades.value = merged
    fillTradesDirection(refs)
    refs.refCounts.value.trades = 'ok'
    refs.idbSyncStatus.value.trades = 'ready'
    refs.log('ok', '缓存', source, `成交加载成功 (${refs.trades.value.length} 条)`)
  } else {
    refs.refCounts.value.trades = 'fail'
    refs.idbSyncStatus.value.trades = 'error'
    refs.log('err', '缓存', 'rpc', '成交加载失败', String(r.reason?.message || r.reason))
  }
}

/**
 * change fix-trades-direction-reversed: 成交方向兜底
 *   broker trd_cfm 推送不带 order_type, 后端 trd.py:87 透传空串到 Trade.order_type='',
 *   前端 row.order_type==='23' 判定空串走 else 分支 → 显示 '卖'.
 *   修复: bootstrap/refresh 路径用 orders 表反查填充 (orders 已先于 trades 写入, 必中).
 */
export function fillTradesDirection(refs) {
  const orders = refs.orders.value
  if (!orders || orders.length === 0) return
  const byOrderNo = new Map(orders.map((o) => [o.order_no, o]))
  let filled = 0
  for (const t of refs.trades.value) {
    if (t.order_type) continue
    const o = byOrderNo.get(t.order_no)
    if (o && o.order_type) {
      t.order_type = o.order_type
      saveTrade(t)
      filled++
    }
  }
  if (filled > 0) {
    refs.log('info', '缓存', 'apply', `成交方向兜底填充 ${filled} 条 + 回写 IDB (broker trd_cfm 漏推 order_type)`)
  }
}
