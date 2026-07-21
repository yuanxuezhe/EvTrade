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
import { saveTrade } from './holdings_idb'

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
    // change fix-trades-direction-reversed: bootstrap/refresh 路径兜底, broker trd_cfm 不带 order_type
    //   从 orders 表反查 order.order_type 填充 trade.order_type (broker 漏推, 后端透传空串)
    _fillTradesDirection(refs)
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
    // change fix-trades-direction-reversed: bootstrap 路径兜底 (orders 已先于 trades 写入, 反查必中)
    _fillTradesDirection(refs)
    refs.refCounts.value.trades = 'ok'
    refs.log('ok', '缓存', source, `成交加载成功 (${refs.trades.value.length} 条)`)
  } else {
    refs.refCounts.value.trades = 'fail'
    refs.log('err', '缓存', 'rpc', '成交加载失败', String(r.reason?.message || r.reason))
  }
}

/**
 * change fix-trades-direction-reversed: 成交方向兜底
 *   broker trd_cfm 推送不带 order_type, 后端 trd.py:87 透传空串到 Trade.order_type='',
 *   前端 row.order_type==='23' 判定空串走 else 分支 → 显示 '卖'.
 *   修复: bootstrap/refresh 路径用 orders 表反查填充 (orders 已先于 trades 写入, 必中).
 *   ws push 路径在 holdings_push.js:140 单独处理.
 */
function _fillTradesDirection(refs) {
  const orders = refs.orders.value
  if (!orders || orders.length === 0) return
  const byOrderNo = new Map(orders.map((o) => [o.order_no, o]))
  let filled = 0
  for (const t of refs.trades.value) {
    if (t.order_type) continue
    const o = byOrderNo.get(t.order_no)
    if (o && o.order_type) {
      t.order_type = o.order_type
      // change fix-trades-direction-reversed-persist: 兜底后回写 IDB (旧 trade.order_type='' 持久化空值)
      saveTrade(t)
      filled++
    }
  }
  if (filled > 0) {
    refs.log('info', '缓存', 'apply', `成交方向兜底填充 ${filled} 条 + 回写 IDB (broker trd_cfm 漏推 order_type)`)
  }
}