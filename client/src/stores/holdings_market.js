/**
 * holdings_market.js — holdings store 实时市值 computed 工厂
 *
 * phase-2 抽取：保持 holdings.js 单 store facade (R3),
 * 把实时市值 / 盈亏 / 收益率 computed 集中
 *
 * 调用者：holdings.js 内部 createMarketComputeds(positions, cachedAsset) → { ... computeds + getters }
 *
 * 不使用全局 useQuoteStore - 调用方注入 quoteStore getter（避免循环依赖）
 */
import { computed } from 'vue'

/**
 * 创建实时市值 / 盈亏 / 收益率 computed + getters
 *
 * @param {Ref<Array>} positions    持仓列表 ref
 * @param {Ref<Object>} cachedAsset 资金 ref
 * @param {Function} getQuoteStore  () => useQuoteStore() 工厂（延迟取 store, 避免循环依赖）
 * @returns liveMarketValue / liveTotalAsset / positionCodes / getLivePrice / getMarketValue / getProfit / getReturnRate
 */
export function createMarketComputeds(positions, cachedAsset, getQuoteStore) {
  /**
   * 实时持仓市值 = sum(quote.last_price * volume) for all positions
   * 行情未到的标的，按 0 计入（不假装有值）
   */
  const liveMarketValue = computed(() => {
    const q = getQuoteStore()
    let sum = 0
    let withQuote = 0
    for (const p of positions.value) {
      const price = q.getLastPrice(p.stock_code)
      if (price != null) {
        // v32: 与 getMarketValue 对齐 — 用 vol (PositionOut.vol)
        sum += price * (Number(p.vol) || 0)
        withQuote++
      }
    }
    return { sum, withQuote, total: positions.value.length }
  })

  /**
   * 实时总资产 = 现金 + 冻结 + 实时市值
   * 初始值（无 quote 时）= 后端 total_asset
   */
  const liveTotalAsset = computed(() => {
    const a = cachedAsset.value
    const mv = liveMarketValue.value.sum
    const allHaveQuote = liveMarketValue.value.withQuote === liveMarketValue.value.total
      && liveMarketValue.value.total > 0
    if (allHaveQuote) {
      return (Number(a.cash) || 0) + (Number(a.frozen_cash) || 0) + mv
    }
    return a.total_asset || 0
  })

  /** 持仓白名单（代码 Set） */
  const positionCodes = computed(() =>
    new Set(positions.value.map((p) => p.stock_code).filter(Boolean))
  )

  function getLivePrice(code) {
    return getQuoteStore().getLastPrice(code) ?? null
  }

  function getMarketValue(p) {
    const price = getLivePrice(p.stock_code)
    if (price == null) return null
    // v32: 与 getProfit/getReturnRate 对齐 — 持仓用 vol, 不是 volume (后端 PositionOut.vol)
    return price * (Number(p.vol) || 0)
  }

  function getProfit(p) {
    const price = getLivePrice(p.stock_code)
    if (price == null) return null
    const cost = Number(p.cost_price) || 0
    const vol = Number(p.vol) || 0
    if (vol === 0) return 0
    return (price - cost) * vol
  }

  function getReturnRate(p) {
    const profit = getProfit(p)
    const cost = Number(p.cost_price) || 0
    const vol = Number(p.vol) || 0
    const costTotal = cost * vol
    if (profit == null || costTotal === 0) return null
    return profit / costTotal
  }

  return {
    liveMarketValue, liveTotalAsset, positionCodes,
    getLivePrice, getMarketValue, getProfit, getReturnRate,
  }
}
