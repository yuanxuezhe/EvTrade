/**
 * holdings_push.js — holdings store ws 推送处理 factory
 *
 * phase-2 抽取：保持 holdings.js 单 store facade (R3),
 * 把 3 个 ws 推送入口（applyXxx）集中
 *
 * 调用者：holdings.js 内部 createPushHandlers({...refs, log, getQuoteStore, recomputeStatus, positionCodes}) → { applyXxx }
 *
 * 3 个入口（与 ws_dispatch.js 协议对齐）:
 *   applyOrderPush    — ws._onOrderCfm 调（含 v8 trd_date 守门、v9 cancel-row 短路、
 *                                          change system-delegation-price-fill-calc: metaMerge/cancel-row 反抹平）
 *   applyTradePush    — ws._onTradeCfm 调（含 v8 trd_date 守门、v9 trade_type 区分、
 *                                          change system-delegation-price-fill-calc: 独立累计 + 反向更新 order；
 *                                          change consolidate-position-data-flow: trade_type=1 cancel-trade 跳过日志标 ok）
 *   applyQuote        — ws._onQuote 调（按 positionCodes 白名单过滤）
 *
 * change consolidate-position-data-flow:
 *   applyPositionPush / applyAssetPush 已删除 (xtquant broker 不发 pos_cfm / ast_cfm)
 *   Position/Asset 状态由 day-init reconcile 覆盖 + holdings.positions/cachedAsset 内存缓存
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
  // v78.3 (REQ-TRADE-032): 不再 import recomputeOrderFromTrade — 后端 ord_cfm 一次写入委托累计, 前端不二次累计
  metaMerge,
  flattenCancelledByRow
} from './holdings_helpers'
import { saveOrder, saveTrade } from './holdings_idb'
import { useT0Stats } from '../composables/useT0Stats'
// v12: IDB 写通 — ws push 时 fire-and-forget 写 IDB (不阻塞 push)
// v13: 改复合 key 单行存 (saveOrder/saveTrade 替代 saveOrdersForDate/saveTradesForDate),
//      O(1) idbPut, 不再读全量 / 写全量

/**
 * 创建 3 个 ws push handler
 *
 * @param deps  { positions, orders, trades, cachedAsset, activeTrdDate, log, positionCodes, getQuoteStore }
 * @returns     { applyOrderPush, applyTradePush, applyQuote }
 */
export function createPushHandlers(deps) {
  const { positions, orders, trades, cachedAsset, activeTrdDate, log, positionCodes, getQuoteStore } = deps
  // 注: consolidate-position-data-flow 后, ws 不再触发 positions / cachedAsset 写。
  //      positions 仍保留引用作为 createPushHandlers 入参 (兼容未来扩展), 但本工厂不读它。

  // v13: IDB 单行写 helper（fire-and-forget, 不阻塞 push）
  //   复合 key 维度: 每次 push 单独写 1 行 (O(1) idbPut), 不再扫全量
  //   间接改 orders 时也单行写, 不再写全量数组
  function _persistOrder(order) {
    saveOrder(order)
  }
  function _persistTrade(trade) {
    saveTrade(trade)
  }
  // change t0-trade-polish-bundle (commit 3): t0Stats 缓存失效
  //   委托/成交推送可能改 today_buy_volume / today_sell_volume / realized_pnl,
  //   推送时 invalid 让下次 useT0Stats.getStats → cache miss → fetch 新值
  function _invalidateT0Stats(code) {
    if (code) useT0Stats.invalidate(code)
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
   *  v13: 返回 final status (普通 row = merged.status, cancel-row = row.status)
   *      供 ws_dispatch._onOrderCfm 调 _notifyOrder 时用 (避免用 broker.status 与表格显示不一致)
   *      - 守门 / 跳过路径返 null (调用方不发通知)
   *  @returns {string|null} final status 码, 跳过返 null
   */
  function applyOrderPush(row, action /* 'open' | 'update' | 'status' */) {
    if (!row || !row.order_no) return null
    // v8 激活日守门
    if (activeTrdDate.value && row.trd_date && row.trd_date !== activeTrdDate.value) {
      log('warn', '交易', 'ws', `委托推送忽略: trd_date=${row.trd_date} != active=${activeTrdDate.value} (${row.stock_code} ${row.order_no})`)
      return null
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
      return row.status
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
    // v13: IDB 单行写 (复合 key 维度, O(1) idbPut)
    _persistOrder(merged)
    // change t0-trade-polish-bundle (commit 3): 委托推送使该标的 t0Stats 缓存失效
    //   下次 useT0Stats.getStats(stock_code) → cache miss → fetch 新值
    _invalidateT0Stats(merged.stock_code)
    return merged.status
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
    // change fix-trades-direction-reversed: broker trd_cfm 不带 order_type, 后端透传空串
    //   前端按 '23'?→'买' 判定空串→'卖' 反了。修复: 反向累计 order 后, 把 order.order_type 写回 trade.
    const newTrade = normalizeTrade({
      trade_id: row.trade_id,
      order_id: row.order_id || '',
      order_no: row.order_no || '',
      trd_date: row.trd_date || todayYYYYMMDD(),
      stock_code: row.stock_code || '',
      order_type: row.order_type || '',   // broker 空 → 下方用 order 兜底
      trade_time: row.trade_time || nowHMS(),
      trade_type: tradeType,
      price: row.price,
      volume: row.volume
    })
    trades.value.unshift(newTrade)
    // v13: IDB 单行写 (复合 key 维度, O(1) idbPut)
    _persistTrade(newTrade)
    // v78.3 (REQ-TRADE-032): 委托累计 (traded_volume/avg_price/traded_amount) 由后端 ord_cfm 一次写入
    //   broker 推完整成交数量+成交均价 → 后端 ord.py 用 broker.traded_volume/traded_price 直接覆盖 Order 表
    //   前端 applyTradePush 不再调 recomputeOrderFromTrade 二次累计 (避免与后端覆盖冲突)
    //   当 trd_cfm 先到 ord_cfm 后到: 表格列在 trd_cfm 后暂时显示旧累计, ord_cfm 后到会自动刷新
    // change fix-trades-direction-reversed: 用 order.order_type 填充 trade.order_type (broker trd_cfm 漏推)
    if (newTrade.order_no) {
      const orderIdx = orders.value.findIndex((o) => o.order_no === newTrade.order_no)
      if (orderIdx >= 0) {
        const updated = orders.value[orderIdx]
        if (!newTrade.order_type && updated.order_type) {
          newTrade.order_type = updated.order_type
          // 同步写回 trades ref + IDB (让前端判定和持久化都对)
          trades.value[0] = newTrade
          _persistTrade(newTrade)
        }
      }
    }
    // change t0-trade-polish-bundle (commit 3): 成交通知使该标的 t0Stats 缓存失效
    //   today_buy_volume / today_sell_volume / realized_pnl 都可能改变 → invalid
    _invalidateT0Stats(newTrade.stock_code)
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

  return { applyOrderPush, applyTradePush, applyQuote }
}
