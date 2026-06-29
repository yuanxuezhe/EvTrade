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
 *   applyOrderPush    — ws._onOrderCfm 调（含 v8 trd_date 守门、v9 cancel-row 短路）
 *   applyTradePush    — ws._onTradeCfm 调（含 v8 trd_date 守门、v9 trade_type 区分）
 *   applyQuote        — ws._onQuote 调（按 positionCodes 白名单过滤）
 */
import { nowHMS, todayYYYYMMDD, recomputeStatus } from './holdings_helpers'
import { putItem } from '../utils/idbStore'

/**
 * 创建 5 个 ws push handler
 *
 * @param deps  { positions, orders, trades, cachedAsset, activeTrdDate, log, positionCodes, getQuoteStore }
 * @returns     { applyPositionPush, applyAssetPush, applyOrderPush, applyTradePush, applyQuote }
 */
export function createPushHandlers(deps) {
  const { positions, orders, trades, cachedAsset, activeTrdDate, log, positionCodes, getQuoteStore } = deps

  /** ws._onPositionCfm 调用：合并持仓推送 + 写日志 + 写 IDB */
  function applyPositionPush(row) {
    if (!row || !row.stock_code) return
    const idx = positions.value.findIndex((p) => p.stock_code === row.stock_code)
    if (idx >= 0) {
      positions.value[idx] = { ...positions.value[idx], ...row }
    } else if (row.volume) {
      positions.value.unshift(row)
    }
    // 增量写 IDB 持仓表 (upsert by stock_code)
    putItem('positions', positions.value[idx] || row).catch((e) => {
      console.warn('[applyPositionPush] IDB 写失败:', e)
    })
    log('info', '交易', 'ws', `持仓推送: ${row.stock_code} → ${row.vol}@${row.cost_price}`)
  }

  /** ws._onAssetCfm 调用：写资金 + 写 IDB */
  function applyAssetPush(row) {
    if (!row) return
    cachedAsset.value = {
      cash: Number(row.cash) || 0,
      frozen_cash: Number(row.frozen_cash) || 0,
      market_value: Number(row.market_value) || 0,
      total_asset: Number(row.total_asset) || 0
    }
    // 写 IDB 资金表 (singleton 覆盖)
    putItem('asset', { id: 'singleton', ...cachedAsset.value }).catch((e) => {
      console.warn('[applyAssetPush] IDB 写失败:', e)
    })
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
   *      - cancel-row volume=0,traded_volume=0,会被推算成 49(已报)污染显示
   *      - cancel-row 由 DELETE 端点写好 status,前端只 merge 不重算
   */
  function applyOrderPush(row, action /* 'open' | 'update' | 'status' */) {
    if (!row || !row.order_no) return
    // v8 激活日守门
    if (activeTrdDate.value && row.trd_date && row.trd_date !== activeTrdDate.value) {
      log('warn', '交易', 'ws', `委托推送忽略: trd_date=${row.trd_date} != active=${activeTrdDate.value} (${row.stock_code} ${row.order_no})`)
      return
    }
    // v9 短路: cancel-row 不走 recomputeStatus (volume=0 会被推算成 49)
    if (Number(row.order_flag) === 1) {
      const idx = orders.value.findIndex((o) => o.order_no === row.order_no)
      if (idx >= 0) {
        orders.value[idx] = { ...orders.value[idx], ...row }
      } else {
        orders.value.unshift(row)
      }
      // 增量写 IDB 委托表 (cancel-row)
      const cancelRow = orders.value[idx] || row
      putItem('orders', cancelRow).catch((e) => {
        console.warn('[applyOrderPush cancel-row] IDB 写失败:', e)
      })
      log('info', '交易', 'ws', `撤单审计: ${row.stock_code} ${row.order_no} status=${row.status} (order_flag=1)`)
      return
    }
    // 防御性重算 status（与后端 _infer_order_status 一致;不传 brokerStatus 完全按 cum/vol 算）
    row.status = recomputeStatus(row).status
    const idx = orders.value.findIndex((o) => o.order_no === row.order_no)
    if (idx >= 0) {
      orders.value[idx] = { ...orders.value[idx], ...row }
      log('info', '交易', 'ws', `委托状态: ${row.stock_code} ${action} (${row.status || ''})`)
    } else {
      orders.value.unshift(row)
      log('info', '交易', 'ws', `新委托: ${row.stock_code} ${row.order_type === '23' ? '买' : '卖'} ${row.volume}@${row.price}`)
    }
    // 增量写 IDB 委托表 (upsert by order_no)
    const finalOrder = orders.value[idx] || row
    putItem('orders', finalOrder).catch((e) => {
      console.warn('[applyOrderPush] IDB 写失败:', e)
    })
  }

  /** ws._onTradeCfm 调用
   *  v8: 守门 = (activeTrdDate, trade_id) → 推送 row.trd_date != active 忽略
   *      成交按 trade_id 唯一, trd_date 是额外维度
   *  v9: 透传 trade_type 字段 (0=normal 1=cancel-fill),日志区分
   */
  function applyTradePush(row) {
    if (!row || !row.trade_id) return
    // v8 激活日守门
    if (activeTrdDate.value && row.trd_date && row.trd_date !== activeTrdDate.value) {
      log('warn', '交易', 'ws', `成交推送忽略: trd_date=${row.trd_date} != active=${activeTrdDate.value} (${row.stock_code})`)
      return
    }
    const idx = trades.value.findIndex((t) => t.trade_id === row.trade_id)
    if (idx < 0) {
      // v7 增: 补全 trd_date / order_no / remark
      //   跟后端 TradeOut schema 对齐 (v6 schema-refinement)
      //   前端做 T 敞口/配平需要 order_no 关联委托
      //   trd_date 用于跨日分组; remark 用于关联 Order.remark = 本地 order_no
      const tradeType = Number(row.trade_type) || 0
      trades.value.unshift({
        trade_id: row.trade_id,
        order_id: row.order_id || '',
        order_no: row.order_no || row.remark || '',  // 兼容 broker 透传 remark
        trd_date: row.trd_date || todayYYYYMMDD(),
        stock_code: row.stock_code || '',
        order_type: row.order_type || '',
        volume: Number(row.volume) || 0,
        price: Number(row.price) || 0,
        amount: Number(row.amount) || Number(row.volume || 0) * Number(row.price || 0),
        trade_time: row.trade_time || nowHMS(),
        trade_type: tradeType  // v9: 0=normal 1=cancel-fill
      })
      if (tradeType === 1) {
        log('ok', '交易', 'ws', `撤单审计: ${row.stock_code} 取消 ${row.volume}@${row.price} (${row.trade_id})`)
      } else {
        log('ok', '交易', 'ws', `成交通知: ${row.stock_code} ${row.order_type === '23' ? '买' : '卖'} ${row.volume}@${row.price}`)
      }
      // 增量写 IDB 成交表 (复合键 [trd_date, trade_id], 直接 put)
      const finalTrade = trades.value[0]
      if (finalTrade) {
        putItem('trades', finalTrade).catch((e) => {
          console.warn('[applyTradePush] IDB 写失败:', e)
        })
      }
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
