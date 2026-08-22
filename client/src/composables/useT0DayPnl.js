/**
 * useT0DayPnl.js — 当日盈亏数据 + 计算 (无轮询, holdings store 驱动)
 *
 * Why:
 *   - 当日盈亏权威在 holdings store: quote-tick 重算写入 positions[].day_pnl,
 *     持仓面板读行字段, 仪表盘 Σ 行字段
 *   - 本模块只做两件事:
 *     1) refresh(trdDate, force) — 拉取 t0-exposure 当日成交聚合 map (买额/卖额/费用)
 *     2) getDayPnl(position)     — 用 quoteStore 实时行情 + 成交 map 算单标的当日盈亏
 *   - 不 import holdings store (避免循环依赖); trdDate 由调用方传入
 *
 * 公式 (lib/t0-calc.calcDayPnl):
 *   (vol×last_price + 今日卖出额) − (last_vol×昨收 + 今日买入额) − 当日费用 day_fee
 *
 * API:
 *   - refresh(trdDate, force=false) → 拉最新成交 map (同日幂等; force 强制重拉)
 *   - getDayPnl(position)           → 单标的当日盈亏 (无行情/无昨收 → null)
 *   - _resetCache()                 → 测试用清空
 */

import { calcDayPnl } from '../lib/t0-calc'
import { t0StatsApi } from '../api/t0_stats'
import { useQuoteStore } from '../stores/quote'

const EMPTY_TRADE = { buy_amount: 0, sell_amount: 0, day_fee: 0 }

// 模块级单例缓存: { [stock_code]: { buy_amount, sell_amount, day_fee } }
// 普通对象即可 — 目标写入在 holdings store 的 positions 行 (响应式由 store 负责)
const _map = {}
let _fetchedTrdDate = null   // 已拉取的交易日 (同日不重复拉; force 忽略)

/**
 * 拉取当日成交聚合 map (t0-exposure user_def='' 全部成交)
 * @param {string|null} trdDate - 8 位 YYYYMMDD (null/'' → 后端默认激活日)
 * @param {boolean} [force=false] - 同日幂等跳过; force=true 强制重拉 (成交推送后)
 */
async function refresh(trdDate, force = false) {
  const td = trdDate || ''
  if (!force && _fetchedTrdDate === td) return
  try {
    const data = await t0StatsApi.getExposure({ userDef: '', trdDate })
    for (const k of Object.keys(_map)) delete _map[k]
    for (const p of data?.positions || []) {
      _map[p.stock_code] = {
        buy_amount: Number(p.buy_amount) || 0,
        sell_amount: Number(p.sell_amount) || 0,
        day_fee: Number(p.day_fee) || 0,
      }
    }
    _fetchedTrdDate = td
  } catch (e) {
    // best-effort: 失败保留旧 map (调用方不中断)
  }
}

/** 单标的当日盈亏 — 无行情/无昨收 → null (调用方: holdings store 的 quote-tick recompute) */
function getDayPnl(position) {
  if (!position || !position.stock_code) return null
  const q = useQuoteStore()
  const code = position.stock_code
  const quote = q.get(code) || null
  const prevClose = quote?.prev_close != null ? Number(quote.prev_close) : null
  const d = _map[code] || EMPTY_TRADE
  return calcDayPnl({
    vol: position.vol,
    last_price: q.getLastPrice(code),
    last_vol: position.last_vol,
    prev_close: prevClose,
    buy_amount: d.buy_amount,
    sell_amount: d.sell_amount,
    day_fee: d.day_fee,
  })
}

/** 单标的当日费用 day_fee — 后端按当日实际买卖成交金额聚合, 与当日盈亏同一费用值
 *  (REQ-FE-534: 浮动盈亏扣费用用; 无成交/未拉取 → 0) */
function getDayFee(position) {
  if (!position || !position.stock_code) return 0
  const d = _map[position.stock_code] || EMPTY_TRADE
  return d.day_fee
}

/** 测试用: 清空成交 map */
function _resetCache() {
  for (const k of Object.keys(_map)) delete _map[k]
  _fetchedTrdDate = null
}

export const useT0DayPnl = {
  refresh,
  getDayPnl,
  getDayFee,
  _resetCache,
}
