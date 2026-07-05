/**
 * useT0Quota.js — T0Trade quota 概览 (change-quota-frame)
 *
 * Why:
 *   - T0Trade 主表行内 4 按钮 (买%/卖%/配平/详情) 但 trader 下单前缺少账户级 quota 概览
 *   - 必须翻 drawer 才知道现金余量/冻结/T+0 可用/今日盈亏 → 多标的轮动快节奏下判断慢
 *   - 顶部 quota frame (5 pill) + 行内可买/可卖列, 让 trader 下单前一眼看清
 *
 * 设计 (与 useT0Stats 同模式):
 *   - 纯函数层 (aggregateQuota + rowQuota): 接受 plain object 入参, 易测
 *   - reactive wrapper (useT0Quota): computed 自动响应 holdings store 变化
 *
 * 颜色阈值 (行内配额列):
 *   - ≥ 1000  → 绿 (quota 充足)
 *   - 100-1000 → 橙 (quota 紧张)
 *   - 1-99    → 红 (quota 极紧, 1 手都买不起)
 *   - = 0     → 灰 (无可用)
 *
 * change change-quota-frame
 */
import { computed } from 'vue'
import { useHoldingsStore } from '../stores/holdings'
import { useQuoteStore } from '../stores/quote'
import { LOT_SIZE } from './useQuickT0'


/**
 * 账户级 quota 聚合 (5 pill 数值来源)
 *
 * @param {Object|null|undefined} asset — cachedAsset {cash, frozen_cash, market_value, ...}
 * @param {Array|null|undefined}  positions — holdings.positions[]
 * @param {Object|null|undefined} t0StatsMap — {stock_code: {realized_pnl, ...}}
 * @returns {{cashAvail: number, frozenCash: number, t0AvailVol: number, todayPnl: number, marketValue: number}}
 */
export function aggregateQuota(asset, positions, t0StatsMap) {
  const a = asset || {}
  const cash = Number(a.cash) || 0
  const frozen = Number(a.frozen_cash) || 0
  const marketValue = Number(a.market_value) || 0

  const posList = Array.isArray(positions) ? positions : []
  const t0AvailVol = posList.reduce((sum, p) => sum + (Number(p?.avl_vol) || 0), 0)

  const stats = t0StatsMap || {}
  let todayPnl = 0
  for (const code of Object.keys(stats)) {
    const s = stats[code]
    if (s && typeof s === 'object') {
      todayPnl += Number(s.realized_pnl) || 0
    }
  }

  return {
    cashAvail: cash - frozen,
    frozenCash: frozen,
    t0AvailVol,
    todayPnl,
    marketValue,
  }
}


/**
 * 行内 quota 余量 (可买 + 可卖)
 *
 * @param {Object|null|undefined} row — 持仓行 {stock_code, vol, avl_vol}
 * @param {number|null|undefined} cash — 可用资金 (asset.cash - frozen_cash)
 * @param {number|null|undefined} price — last_price (来自 quoteStore.getLastPrice)
 * @returns {{maxBuyable: number, maxSellable: number}}
 */
export function rowQuota(row, cash, price) {
  const code = row?.stock_code
  if (!code) return { maxBuyable: 0, maxSellable: 0 }

  // 可卖 = avl_vol 直接读
  const maxSellable = Number(row?.avl_vol) || 0

  // 可买 = floor(cash / price / LOT_SIZE) * LOT_SIZE
  const p = Number(price)
  const c = Number(cash) || 0
  if (!Number.isFinite(p) || p <= 0 || c <= 0) {
    return { maxBuyable: 0, maxSellable }
  }
  const maxBuyable = Math.floor(c / p / LOT_SIZE) * LOT_SIZE
  return { maxBuyable, maxSellable }
}


/**
 * quota 颜色等级 (行内配额列文字色)
 *   - >= 1000 → 'high' (绿)
 *   - 100-999 → 'mid'  (橙)
 *   - 1-99    → 'low'  (红)
 *   - 0       → 'none' (灰)
 *
 * @param {number} n
 * @returns {'high'|'mid'|'low'|'none'}
 */
export function quotaLevel(n) {
  const v = Number(n) || 0
  if (v >= 1000) return 'high'
  if (v >= 100) return 'mid'
  if (v > 0) return 'low'
  return 'none'
}


/**
 * T0Trade quota reactive wrapper
 *
 *   aggregate: computed 5 pill 数值 (依赖 cachedAsset + positions + t0StatsMap)
 *   rowQuota:  (row) → 单行 quota (依赖 last_price + cashAvail)
 *
 * t0StatsMap 是 T0Trade.vue local ref (via useT0Stats.loadAll),
 * 调用方须显式传入 (而非 hook 内部抓, 避免持有过时引用)
 *
 * 依赖 holdings.cachedAsset / holdings.positions (自动响应)
 */
export function useT0Quota(t0StatsMapRef) {
  const holdings = useHoldingsStore()
  const quoteStore = useQuoteStore()

  const aggregate = computed(() => aggregateQuota(
    holdings.cachedAsset,
    holdings.positions,
    t0StatsMapRef?.value || {}
  ))

  function rowQuotaFor(row) {
    const price = quoteStore.getLastPrice(row?.stock_code)
    return rowQuota(row, aggregate.value.cashAvail, price)
  }

  return { aggregate, rowQuota: rowQuotaFor }
}