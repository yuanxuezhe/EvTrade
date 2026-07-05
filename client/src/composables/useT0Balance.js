import { ref, computed, watch } from 'vue'
import { useQuoteStore } from '../stores/quote'
import { useHoldingsStore } from '../stores/holdings'
import { useAssetStore } from '../stores/asset'
import { storeToRefs } from 'pinia'
import { t0StatsApi } from '../api/t0_stats'
import {
  roundToLot as _roundToLot,
  calcInsufficientCash as _calcInsufficientCash,
  calcInsufficientPosition as _calcInsufficientPosition,
} from '../lib/t0-calc'

/**
 * T0 配平计算 composable
 *
 * 用法：
 *   const {
 *     currentVolume, available, cost, marketValue, profit, profitRate,
 *     targetVolume, setTargetVolume,
 *     delta, deltaAmount, balanceQty, balanceAmount,
 *     isStale, hasQuote,
 *   } = useT0Balance('600519')
 *
 * 计算规则（与后端 t0.py 一致）：
 *   - 配平 = target - current
 *   - 配平系数 0..2（默认 1.0 = 100% 配平）
 *   - 整手取整 100 股
 *   - 买/卖方向自动判定
 *   - 限价 = 当前价 ± 0.01（最新价 = 11，对手价 = 14，五档 = 默认 11）
 */
export function useT0Balance(stockCodeRef) {
  const quote = useQuoteStore()
  const holdings = useHoldingsStore()
  const asset = useAssetStore()
  const { positions } = storeToRefs(holdings)
  const { asset: assetData } = storeToRefs(asset)

  // 目标持仓（双向绑定的 ref）
  const targetVolume = ref(0)
  // 配平系数 0..2
  const balanceCoeff = ref(1.0)
  // 限价类型
  const priceType = ref('latest')   // 'latest' | 'oppose' | 'limit' | 'market'
  // 限价（手动覆盖，仅 priceType=limit 时生效）
  const limitPrice = ref(null)

  // 当前持仓（响应式 - positions 变化或 stockCode 变化时重算）
  const currentPosition = computed(() => {
    const code = typeof stockCodeRef === 'string' ? stockCodeRef : stockCodeRef.value
    if (!code) return null
    return positions.value.find((p) => p.stock_code === code) || null
  })

  const currentVolume = computed(() => {
    const p = currentPosition.value
    if (!p) return 0
    // 优先用 avl_vol（可用持仓 = 持仓 - 已挂卖单），无则用 vol
    return Number(p.avl_vol ?? p.vol ?? 0)
  })

  const cost = computed(() => {
    const p = currentPosition.value
    return p ? Number(p.cost_price) || 0 : 0
  })

  // 实时行情
  const lastPrice = computed(() => quote.getLastPrice(
    typeof stockCodeRef === 'string' ? stockCodeRef : stockCodeRef.value
  ))
  const changePct = computed(() => quote.getChangePct(
    typeof stockCodeRef === 'string' ? stockCodeRef : stockCodeRef.value
  ))

  // 行情是否新鲜（30s 内）
  const isStale = computed(() => {
    const code = typeof stockCodeRef === 'string' ? stockCodeRef : stockCodeRef.value
    const q = quote.get(code)
    if (!q) return true
    return (Date.now() - (q.ts || 0)) > 30_000
  })
  const hasQuote = computed(() => lastPrice.value != null)

  // 实时市值 / 浮盈
  const marketValue = computed(() => {
    if (!hasQuote.value) return 0
    return lastPrice.value * currentVolume.value
  })
  const costTotal = computed(() => cost.value * currentVolume.value)
  const profit = computed(() => {
    if (!hasQuote.value) return 0
    return (lastPrice.value - cost.value) * currentVolume.value
  })
  const profitRate = computed(() => {
    if (costTotal.value === 0) return 0
    return profit.value / costTotal.value
  })

  // ---- 配平算法 -------------------------------------------------------
  // 差额 = 目标 - 当前
  const delta = computed(() => targetVolume.value - currentVolume.value)
  // 差额方向: 'buy' | 'sell' | 'flat'
  const direction = computed(() => {
    if (delta.value > 0) return 'buy'
    if (delta.value < 0) return 'sell'
    return 'flat'
  })

  // 整手取整 + 配平系数（与后端 calc_t0_volume 对齐）
  // 应用 balanceCoeff 后委托 @/lib/t0-calc.roundToLot 做纯取整 (单一权威源)
  const roundToLot = (qty, lot = 100) => {
    if (qty === 0) return 0
    const sign = qty > 0 ? 1 : -1
    return _roundToLot(sign * Math.abs(qty) * balanceCoeff.value, lot)
  }

  // 配平后的实际下单数
  const balanceQty = computed(() => roundToLot(delta.value))
  // 配平所需资金
  const balanceAmount = computed(() => {
    if (!hasQuote.value || balanceQty.value === 0) return 0
    return Math.abs(balanceQty.value) * lastPrice.value
  })

  // ---- 下单价格 -------------------------------------------------------
  const orderPrice = computed(() => {
    if (priceType.value === 'market') return 0  // 0 = 市价
    if (priceType.value === 'limit') return Number(limitPrice.value) || lastPrice.value || 0
    if (!hasQuote.value) return 0
    if (priceType.value === 'oppose') {
      // 对手价: 买用卖1价 / 卖用买1价
      const code = typeof stockCodeRef === 'string' ? stockCodeRef : stockCodeRef.value
      const q = quote.get(code)
      if (direction.value === 'buy') {
        return Number(q?.fields?.[9]) || lastPrice.value   // 卖1价
      } else if (direction.value === 'sell') {
        return Number(q?.fields?.[14]) || lastPrice.value  // 买1价
      }
    }
    // 'latest' = 限价最新价
    return lastPrice.value
  })

  // ---- 一键动作 -------------------------------------------------------
  // 一键全仓买：按可用资金 + 配平系数
  const oneClickBuyQty = computed(() => {
    const cash = Number(assetData.value?.cash) || 0
    if (!hasQuote.value || cash <= 0) return 0
    return roundToLot(cash / lastPrice.value)
  })
  // 一键全仓卖：当前可用持仓
  const oneClickSellQty = computed(() => currentVolume.value)

  // 一键配平：套 balanceQty
  const oneClickBalanceQty = computed(() => balanceQty.value)

  // 资金校验：买方向所需资金 > 现金？ (委托 lib/t0-calc.calcInsufficientCash, 保留 boolean API)
  const insufficientCash = computed(() => !_calcInsufficientCash({
    side: direction.value,
    qty: balanceQty.value,
    price: lastPrice.value,
    cash: assetData.value?.cash,
  }).ok)
  // 持仓校验：卖方向所需股数 > 可用？ (委托 lib/t0-calc.calcInsufficientPosition)
  const insufficientPosition = computed(() => !_calcInsufficientPosition({
    side: direction.value,
    qty: balanceQty.value,
    currentVolume: currentVolume.value,
  }).ok)

  // ---- 切换 stockCode 时，重置目标持仓为 currentVolume ----
  watch(currentVolume, (v) => {
    targetVolume.value = v
  }, { immediate: true })

  function setTargetVolume(v) {
    targetVolume.value = Math.max(0, Math.floor(Number(v) || 0))
  }

  // ---- 多标的敞口聚合（user_def='T0'） ----
  const exposureList = ref([])            // [{stock_code, buy_vol, sell_vol, net_vol, ...}]
  const exposureTotals = ref(null)        // {buy_vol, sell_vol, net_vol, realized_pnl, ...}
  const exposureLoading = ref(false)
  async function loadExposure(userDef = 'T0', trdDate = null, onError = null) {
    exposureLoading.value = true
    try {
      const data = await t0StatsApi.getExposure({ userDef, trdDate })
      exposureList.value = data.positions || []
      exposureTotals.value = data.totals || null
    } catch (e) {
      console.warn('[useT0Balance] loadExposure failed:', e)
      exposureList.value = []
      exposureTotals.value = null
      if (typeof onError === 'function') onError(e)
    } finally {
      exposureLoading.value = false
    }
  }

  // ---- 跨期累计（user_def='T0'，days=7/30/90） ----
  const aggregate = ref(null)            // {summary, by_day, by_stock}
  const aggregateLoading = ref(false)
  async function loadAggregate(userDef = 'T0', days = 30, onError = null) {
    aggregateLoading.value = true
    try {
      aggregate.value = await t0StatsApi.getAggregate({ userDef, days })
    } catch (e) {
      console.warn('[useT0Balance] loadAggregate failed:', e)
      aggregate.value = null
      if (typeof onError === 'function') onError(e)
    } finally {
      aggregateLoading.value = false
    }
  }

  // 衍生：哪些敞口需要一键配平（net_vol 绝对值 >= 100）
  const needRebalance = computed(() =>
    exposureList.value.filter((p) => Math.abs(p.net_volume) >= 100)
  )

  return {
    // state
    targetVolume, balanceCoeff, priceType, limitPrice,
    // 当前持仓
    currentPosition, currentVolume, cost, available: currentVolume,
    // 行情
    lastPrice, changePct, isStale, hasQuote,
    // 盈亏
    marketValue, costTotal, profit, profitRate,
    // 配平
    delta, direction, balanceQty, balanceAmount,
    // 下单价
    orderPrice,
    // 一键
    oneClickBuyQty, oneClickSellQty, oneClickBalanceQty,
    // 校验
    insufficientCash, insufficientPosition,
    // 敞口聚合
    exposureList, exposureTotals, exposureLoading, loadExposure, needRebalance,
    // 跨期累计
    aggregate, aggregateLoading, loadAggregate,
    // actions
    setTargetVolume, roundToLot
  }
}
