/**
 * holdings_apply_results.js — 持仓 store 单资源结果应用 helper
 *
 * 把 Promise.allSettled 的结果（{status, value|reason}）应用到 holdings store 的 ref：
 *   - 成功：写 ref + 更新 refCounts + 写日志（bootstrap）或返回 summary（refresh）
 *   - 失败：标记 refCounts='fail' + 写错误日志
 *
 * 两套 helper：
 *   - _applyXxxResult(r, source)        — bootstrap 用，写"加载成功"日志
 *   - _applyXxxRefreshResult(r)         — refreshAll 用，返回 summary 字符串
 *
 * 调用者：holdings_bootstrap.js 内的 createBootstrap 工厂
 *
 * change system-delegation-price-fill-calc:
 *   applyOrdersRefresh/applyOrdersResult   — 调 normalizeOrder 重算 avg_price + status
 *   applyTradesRefresh/applyTradesResult   — map 调 normalizeTrade 重算 amount
 */
import { parseAsset, normalizeOrder, normalizeTrade } from './holdings_helpers'

// ---- refreshAll 用：返回 summary 字符串 --------------------------------

export function applyAssetRefresh(r, refs) {
  if (r.status === 'fulfilled') {
    const a = parseAsset(r.value)
    if (a) refs.cachedAsset.value = a
    refs.refCounts.value.asset = 'ok'
    return `资金 ¥${(a?.total_asset || 0).toLocaleString()}`
  }
  refs.refCounts.value.asset = 'fail'
  refs.log('err', '缓存', 'rpc', '资金刷新失败', String(r.reason?.message || r.reason))
  return null
}

export function applyPositionsRefresh(r, refs) {
  if (r.status === 'fulfilled') {
    refs.positions.value = Array.isArray(r.value) ? r.value : []
    refs.refCounts.value.positions = 'ok'
    return `持仓 ${refs.positions.value.length} 只`
  }
  refs.refCounts.value.positions = 'fail'
  refs.log('err', '缓存', 'rpc', '持仓刷新失败', String(r.reason?.message || r.reason))
  return null
}

export function applyOrdersRefresh(r, refs) {
  if (r.status === 'fulfilled') {
    // change system-delegation-price-fill-calc: 保留 row 累计字段, 重算 avg_price + status
    const rawOrders = Array.isArray(r.value) ? r.value : []
    refs.orders.value = rawOrders.map(normalizeOrder)
    refs.refCounts.value.orders = 'ok'
    return `委托 ${refs.orders.value.length} 条`
  }
  refs.refCounts.value.orders = 'fail'
  refs.log('err', '缓存', 'rpc', '委托刷新失败', String(r.reason?.message || r.reason))
  return null
}

export function applyTradesRefresh(r, refs) {
  if (r.status === 'fulfilled') {
    // change system-delegation-price-fill-calc: amount 本地算 (price × volume)
    const rawTrades = Array.isArray(r.value) ? r.value : []
    refs.trades.value = rawTrades.map(normalizeTrade)
    refs.refCounts.value.trades = 'ok'
    return `成交 ${refs.trades.value.length} 条`
  }
  refs.refCounts.value.trades = 'fail'
  refs.log('err', '缓存', 'rpc', '成交刷新失败', String(r.reason?.message || r.reason))
  return null
}

// ---- bootstrap 用：写"加载成功"日志 ----------------------------------

export function applyAssetResult(r, refs, source) {
  if (r.status === 'fulfilled') {
    const a = parseAsset(r.value)
    if (a) refs.cachedAsset.value = a
    refs.refCounts.value.asset = 'ok'
    refs.log('ok', '缓存', source, `资金加载成功 (¥${(a?.total_asset || 0).toLocaleString()})`)
  } else {
    refs.refCounts.value.asset = 'fail'
    refs.log('err', '缓存', 'rpc', '资金加载失败', String(r.reason?.message || r.reason))
  }
}

export function applyPositionsResult(r, refs, source) {
  if (r.status === 'fulfilled') {
    // 后端返 {code:0, list:[...]}，解 .list
    refs.positions.value = Array.isArray(r.value) ? r.value
      : (Array.isArray(r.value?.list) ? r.value.list : [])
    refs.refCounts.value.positions = 'ok'
    refs.log('ok', '缓存', source, `持仓加载成功 (${refs.positions.value.length} 只)`)
  } else {
    refs.refCounts.value.positions = 'fail'
    refs.log('err', '缓存', 'rpc', '持仓加载失败', String(r.reason?.message || r.reason))
  }
}

export function applyOrdersResult(r, refs, source) {
  if (r.status === 'fulfilled') {
    const rawOrders = Array.isArray(r.value) ? r.value
      : (Array.isArray(r.value?.list) ? r.value.list : [])
    // change system-delegation-price-fill-calc: 保留 row 累计字段, 重算 avg_price + status
    refs.orders.value = rawOrders.map(normalizeOrder)
    refs.refCounts.value.orders = 'ok'
    refs.log('ok', '缓存', source, `委托加载成功 (${refs.orders.value.length} 条)`)
  } else {
    refs.refCounts.value.orders = 'fail'
    refs.log('err', '缓存', 'rpc', '委托加载失败', String(r.reason?.message || r.reason))
  }
}

export function applyTradesResult(r, refs, source) {
  if (r.status === 'fulfilled') {
    // change system-delegation-price-fill-calc: amount 本地算 (price × volume)
    const rawTrades = Array.isArray(r.value) ? r.value
      : (Array.isArray(r.value?.list) ? r.value.list : [])
    refs.trades.value = rawTrades.map(normalizeTrade)
    refs.refCounts.value.trades = 'ok'
    refs.log('ok', '缓存', source, `成交加载成功 (${refs.trades.value.length} 条)`)
  } else {
    refs.refCounts.value.trades = 'fail'
    refs.log('err', '缓存', 'rpc', '成交加载失败', String(r.reason?.message || r.reason))
  }
}