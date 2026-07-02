/**
 * holdings_push.js — holdings store ws 推送处理 factory
 *
 * phase-2 抽取：保持 holdings.js 单 store facade (R3),
 * 把 5 个 ws 推送入口（applyXxx）集中
 *
 * 调用者：holdings.js 内部 createPushHandlers({...refs, log, getQuoteStore, recomputeStatus, positionCodes}) → { applyXxx }
 *
 * 5 个入口（与 ws_dispatch.js 协议对齐）:
 *   applyPositionPush — ws._onPositionCfm 调
 *   applyAssetPush    — ws._onAssetCfm 调
 *   applyOrderPush    — ws._onOrderCfm 调（含 v8 trd_date 守门、v9 cancel-row 短路、
 *                                          change system-delegation-price-fill-calc: metaMerge/cancel-row 反抹平）
 *   applyTradePush    — ws._onTradeCfm 调（含 v8 trd_date 守门、v9 trade_type 区分、
 *                                          change system-delegation-price-fill-calc: 独立累计 + 反向更新 order）
 *   applyQuote        — ws._onQuote 调（按 positionCodes 白名单过滤）
 *
 * change system-delegation-price-fill-calc: 推送仅含单笔成交/委托元数据,
 * 前后端独立累计: ws push 改 orders.value 时通过 metaMerge 保留 ref 累计;
 *                 ws push 改 trades.value 时 normalizeTrade + 反向 recomputeOrderFromTrade 累计对应 order.
 */
import {
  nowHMS,
  todayYYYYMMDD,
  recomputeStatus,
  normalizeTrade,
  recomputeOrderFromTrade,
  metaMerge,
  flattenCancelledByRow
} from './holdings_helpers'
// 注: 之前的 IDB 持久化已废弃. 当前架构纯 Pinia 内存, ws push 只改内存.

/**
 * 创建 5 个 ws push handler
 *
 * @param deps  { positions, orders, trades, cachedAsset, activeTrdDate, log, positionCodes, getQuoteStore }
 * @returns     { applyPositionPush, applyAssetPush, applyOrderPush, applyTradePush, applyQuote }
 */
export function createPushHandlers(deps) {
  const { positions, orders, trades, cachedAsset, activeTrdDate, log, positionCodes, getQuoteStore } = deps

  /** ws._onPositionCfm 调用：合并持仓推送 + 写日志 */
  function applyPositionPush(row) {
    if (!row || !row.stock_code) return
    const idx = positions.value.findIndex((p) => p.stock_code === row.stock_code)
    if (idx >= 0) {
      positions.value[idx] = { ...positions.value[idx], ...row }
    } else if (row.volume) {
      positions.value.unshift(row)
    }
    log('info', '交易', 'ws', `持仓推送: ${row.stock_code} → ${row.vol}@${row.cost_price}`)
  }

  /** ws._onAssetCfm 调用：写资金 */
  function applyAssetPush(row) {
    if (!row) return
    cachedAsset.value = {
      cash: Number(row.cash) || 0,
      frozen_cash: Number(row.frozen_cash) || 0,
      market_value: Number(row.market_value) || 0,
      total_asset: Number(row.total_asset) || 0
    }
    log('info', '交易', 'ws', `资产推送: 总资产 ¥${cachedAsset.value.total_asset.toLocaleString()}`)
  }

  /** ws._onOrderCfm 调用：合并委托 + 写日志
   *  v6: 匹配键用 order_no（本地 8 位序号 PK），order_id 可能为 null
   *      收到推送时调前端 inferOrderStatus 防御性重算 status
   *  v8: 守门 = (activeTrdDate, order_no)
   *      - 推送 row.trd_date != activeTrdDate → 忽略（broker 偶尔推老委托的历史变更）
   *      - activeTrdDate == null（降级）→ 放行（log warn）
   *      - 已有订单的 trd_date 也要守门（防止 push 覆盖跨日缓存）
   *  v9: cancel-row (order_flag=1) 短路 recomputeStatus
   *      - cancel-row volume=0,traded_volume=0,会被推算成 50(已报 broker xtconstant)污染显示
   *      - cancel-row 由 DELETE 端点写好 status(54=broker 已撤 / 57=broker 废单),前端只 merge 不重算
   *  change system-delegation-price-fill-calc:
   *      - 普通 row: 调 metaMerge(row, ref) 仅覆盖 PK + 元数据, ref 累计字段保留
   *      - cancel-row: 写 cancel-row 自身 + 调 flattenCancelledByRow 反向抹平原委托 cancelled_volume
   */
  function applyOrderPush(row, action /* 'open' | 'update' | 'status' */) {
    if (!row || !row.order_no) return
    // v8 激活日守门
    if (activeTrdDate.value && row.trd_date && row.trd_date !== activeTrdDate.value) {
      log('warn', '交易', 'ws', `委托推送忽略: trd_date=${row.trd_date} != active=${activeTrdDate.value} (${row.stock_code} ${row.order_no})`)
      return
    }
    // v9 短路: cancel-row (order_flag=1) 不走 metaMerge（其 status 由 DELETE 端点写死, 不重算）
    if (Number(row.order_flag) === 1) {
      const idx = orders.value.findIndex((o) => o.order_no === row.order_no)
      if (idx >= 0) {
        orders.value[idx] = { ...orders.value[idx], ...row }
      } else {
        orders.value.unshift(row)
      }
      // change: 反向抹平原委托 cancelled_volume (R1 兜底, 与后端 orig.cancelled_volume = volume 对齐)
      const affected = flattenCancelledByRow(row, orders.value)
      for (const { index, newValue } of affected) {
        orders.value[index] = newValue
      }
      const flattenInfo = affected.length > 0
        ? `, flatten orig[${affected.map((a) => a.index).join(',')}]`
        : ''
      log('info', '交易', 'ws', `撤单审计: ${row.stock_code} ${row.order_no} status=${row.status} (order_flag=1${flattenInfo})`)
      return
    }
    // change: 普通 row 走 metaMerge — 仅覆盖 PK + 元数据, ref 累计字段保留
    // status 在 metaMerge 内部由 inferOrderStatus(ref 累计 + 可选 row.status) 重推断
    const idx = orders.value.findIndex((o) => o.order_no === row.order_no)
    const ref = idx >= 0 ? orders.value[idx] : null
    const merged = metaMerge(row, ref)
    if (idx >= 0) {
      orders.value[idx] = merged
      log('info', '交易', 'ws', `委托状态: ${merged.stock_code} ${action} (${merged.status || ''})`)
    } else {
      orders.value.unshift(merged)
      log('info', '交易', 'ws', `新委托: ${merged.stock_code} ${merged.order_type === '23' ? '买' : '卖'} ${merged.volume}@${merged.price}`)
    }
  }

  /** ws._onTradeCfm 调用
   *  v8: 守门 = (activeTrdDate, trade_id) → 推送 row.trd_date != active 忽略
   *      成交按 trade_id 唯一, trd_date 是额外维度
   *  v9: 透传 trade_type 字段 (0=normal 1=cancel-fill),日志区分
   *  change system-delegation-price-fill-calc:
   *      - amount = price × volume (本地算, 不信任 broker.traded_amount)
   *      - 按 trade_id 去重 (已有则跳过)
   *      - 按 order_no 在 orders 中定位父委托, 调 recomputeOrderFromTrade 增量累计
   */
  function applyTradePush(row) {
    if (!row || !row.trade_id) return
    // v8 激活日守门
    if (activeTrdDate.value && row.trd_date && row.trd_date !== activeTrdDate.value) {
      log('warn', '交易', 'ws', `成交推送忽略: trd_date=${row.trd_date} != active=${activeTrdDate.value} (${row.stock_code})`)
      return
    }
    // change: 按 trade_id 去重
    if (trades.value.some((t) => t.trade_id === row.trade_id)) return

    const tradeType = Number(row.trade_type) || 0
    // change: 标准化 amount = price × volume (本地算)
    const newTrade = normalizeTrade({
      trade_id: row.trade_id,
      order_id: row.order_id || '',
      order_no: row.order_no || '',
      trd_date: row.trd_date || todayYYYYMMDD(),
      stock_code: row.stock_code || '',
      order_type: row.order_type || '',
      trade_time: row.trade_time || nowHMS(),
      trade_type: tradeType,
      price: row.price,
      volume: row.volume
    })
    trades.value.unshift(newTrade)
    // change: 反向累计 orders 中的对应委托
    if (newTrade.order_no) {
      const orderIdx = orders.value.findIndex((o) => o.order_no === newTrade.order_no)
      if (orderIdx >= 0) {
        const old = orders.value[orderIdx]
        const updated = recomputeOrderFromTrade(old, newTrade)
        orders.value[orderIdx] = updated
        log('info', '交易', 'ws', `订单累计: ${updated.stock_code} ${updated.order_no} ${updated.traded_volume}/${updated.volume} status=${updated.status}`)
      }
    }
    if (tradeType === 1) {
      log('ok', '交易', 'ws', `撤单审计: ${newTrade.stock_code} 取消 ${newTrade.volume}@${newTrade.price} (${newTrade.trade_id})`)
    } else {
      log('ok', '交易', 'ws', `成交通知: ${newTrade.stock_code} ${String(newTrade.order_type) === '23' ? '买' : '卖'} ${newTrade.volume}@${newTrade.price}`)
    }
  }

  /** ws._onQuote 调用：白名单过滤 + 写入 quote store */
  function applyQuote(row) {
    if (!row || !row.stock_code) return false
    if (!positionCodes.value.has(row.stock_code)) return false
    const q = getQuoteStore()
    q.update({
      stock_code: row.stock_code,
      last_price: row.last_price,
      fields: row.fields,
      body: row.body,
      ts: row.ts || Date.now()
    })
    return true
  }

  return { applyPositionPush, applyAssetPush, applyOrderPush, applyTradePush, applyQuote }
}
