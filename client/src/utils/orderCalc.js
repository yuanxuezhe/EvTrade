/**
 * orderCalc.js — 前端独立计算委托 / 成交缓存工具
 *
 * change system-delegation-price-fill-calc: 推送仅含单笔成交/委托元数据,
 * 前端必须独立累计 + 推断 status + 标准化 amount.
 * 5 个纯函数（无 Pinia / 无副作用 / 不可变返回新对象）:
 *
 *   normalizeTrade(trade)            — trades.amount = price × volume 本地算
 *   recomputeOrderFromTrade(o, t)    — 增量累计 + status 推断
 *   metaMerge(row, ref)              — 仅覆盖 PK + 元数据, 累计字段保留 ref
 *   flattenCancelledByRow(row, list) — cancel-row 反向抹平原委托 cancelled_volume
 *   normalizeOrder(o)                — bootstrap/refresh 用: 重算 avg_price + status
 */

import { inferOrderStatus } from './format'

/**
 * 标准化成交行: amount = price × volume 本地算,丢弃 broker 推的 amount 字段
 */
export function normalizeTrade(trade) {
  return {
    ...trade,
    amount: (Number(trade.price) || 0) * (Number(trade.volume) || 0),
  }
}

/**
 * 增量累计: 把 trade 累加到 order, 重算 avg_price, 推断 status
 */
export function recomputeOrderFromTrade(order, trade) {
  const tv = (Number(order.traded_volume) || 0) + (Number(trade.volume) || 0)
  const ta = (Number(order.traded_amount) || 0)
    + ((Number(trade.price) || 0) * (Number(trade.volume) || 0))
  const avg = tv > 0 ? ta / tv : 0
  const next = {
    ...order,
    traded_volume: tv,
    traded_amount: ta,
    avg_price: avg,
  }
  next.status = inferOrderStatus(next, null)
  return next
}

/**
 * ws order_update 合并: 仅覆盖 PK + 元数据, ref 的累计字段全部保留
 * (traded_volume / traded_amount / avg_price / cancelled_volume 不被 row 覆盖)
 * 但 status 用 row.status 作 broker_status 信号调 inferOrderStatus 重推断
 *
 * v65 (REQ-TRADE-025): 补 task_id 字段透传.
 *   之前 metaMerge 漏 task_id, 导致 T0 下单后 _upsertToHoldings(order) → applyOrderPush
 *   → metaMerge 丢 task_id (merged.task_id=undefined). 重刷 bootstrap 才会回填.
 *   修复: row.task_id ?? ref.task_id ?? null 写回 merged.
 *
 * v66 (REQ-TRADE-026): 补 strategy_type 字段透传.
 *   之前 v65 修了 task_id 但同样模式下 strategy_type 也是 PK 元数据 (不会变化),
 *   必须 row.strategy_type ?? ref.strategy_type ?? 0 写回 merged, 否则 T0Trade 缓存 filter 失效.
 *   后端 Pydantic Literal[0,1] default 0 + ORM NOT NULL DEFAULT 0, 前端兜底 0.
 */
export function metaMerge(row, ref = {}) {
  const merged = {
    ...ref,
    order_no: row.order_no || ref.order_no || '',
    trd_date: row.trd_date || ref.trd_date || '',
    order_id: row.order_id ?? ref.order_id ?? '',
    user_def: row.user_def ?? ref.user_def ?? '',
    order_time: row.order_time ?? ref.order_time ?? '',
    stock_code: row.stock_code ?? ref.stock_code ?? '',
    order_type: row.order_type ?? ref.order_type ?? '',
    price_type: row.price_type ?? ref.price_type ?? 0,
    price: Number(row.price ?? ref.price ?? 0),
    volume: Number(row.volume ?? ref.volume ?? 0),
    status_msg: row.status_msg ?? ref.status_msg ?? '',
    // v65 (REQ-TRADE-025): 透传 task_id 供 T0Trade 委托明细 filter + cache 列展示.
    // 之前 metaMerge 漏, 导致 T0 下单后 _upsertToHoldings → applyOrderPush → metaMerge 丢 task_id.
    task_id: row.task_id ?? ref.task_id ?? null,
    // v66 (REQ-TRADE-026): 透传 strategy_type 供缓存过滤 (T0Trade filter strategy_type=1) + cache 列展示.
    //   与 task_id 同模式: 行级元数据, row 优先, ref 兜底, 默认 0.
    strategy_type: row.strategy_type ?? ref.strategy_type ?? 0,
  }
  merged.status = inferOrderStatus(merged, row.status || null)
  return merged
}

/**
 * cancel-row 反向抹平: 由 user_def='CANCEL:{orig_order_no}' 找到原委托,
 * 把 orig.cancelled_volume = orig.volume (R1/R2a 语义) + 重推断 status
 *
 * @returns {Array} 受影响原委托数组（便于调用方触发响应式更新）
 */
export function flattenCancelledByRow(row, list) {
  const userDef = String(row.user_def || '')
  if (!userDef.startsWith('CANCEL:')) return []
  const origOrderNo = userDef.slice('CANCEL:'.length)
  const idx = list.findIndex(o => o.order_no === origOrderNo)
  if (idx < 0) return []
  const orig = list[idx]
  const updated = { ...orig, cancelled_volume: Number(orig.volume) || 0 }
  updated.status = inferOrderStatus(updated, null)
  list[idx] = updated
  return [list[idx]]
}

/**
 * 标准化委托行（bootstrap / refresh 用）: 重算 avg_price + 重推断 status
 * 保留 row.traded_volume / row.traded_amount / row.cancelled_volume 原值,
 * 仅重算派生字段. 不做增量累计(那是 recomputeOrderFromTrade 的事).
 */
export function normalizeOrder(o) {
  const tv = Number(o.traded_volume) || 0
  const ta = Number(o.traded_amount) || 0
  const avg = tv > 0 ? ta / tv : 0
  const next = {
    ...o,
    avg_price: avg,
  }
  next.status = inferOrderStatus(next, null)
  return next
}