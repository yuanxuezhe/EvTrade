/**
 * usePricePrecision composable — v80 价格精度统一入口
 *
 * 设计:
 * - 输入 stockCode (ref 或 string), 返回响应式的 precision 数值 (0~6)
 * - 走 stocks store 的 stockScale() helper, 读 cache, cache miss 兜底 2
 * - Vue 组件内 :precision="precision" 即可让 el-input-number 按 scale round
 *
 * 用法:
 *   const { precision, formatPrice, stktype } = usePricePrecision(() => stockCode.value)
 *   <el-input-number :precision="precision" />
 *   <span>{{ formatPrice(price) }}</span>
 */
import { computed, unref } from 'vue'
import { useStocksStore } from '../stores/stocks'

export function usePricePrecision(stockCodeGetter) {
  const stocksStore = useStocksStore()

  const precision = computed(() => {
    const code = typeof stockCodeGetter === 'function'
      ? stockCodeGetter()
      : unref(stockCodeGetter)
    return stocksStore.stockScale(code)
  })

  const stktype = computed(() => {
    const code = typeof stockCodeGetter === 'function'
      ? stockCodeGetter()
      : unref(stockCodeGetter)
    return stocksStore.stockStktype(code)
  })

  /**
   * 按 scale 四舍五入显示价格 (前端展示用)
   */
  function formatPrice(price, stockCode) {
    if (price === null || price === undefined || price === '') return ''
    const n = Number(price)
    if (!Number.isFinite(n)) return ''
    // v82: 支持每行按 row.stock_code 计算精度
    const p = stockCode !== undefined
      ? stocksStore.stockScale(stockCode)
      : precision.value
    return n.toFixed(p)
  }

  /**
   * 按 scale round 价格 (下单前用, 与后端 place_order round 逻辑对齐)
   */
  function roundPrice(price) {
    if (price === null || price === undefined || price === '') return 0
    const n = Number(price)
    if (!Number.isFinite(n)) return 0
    const p = precision.value
    const m = Math.pow(10, p)
    return Math.round(n * m) / m
  }

  return { precision, stktype, formatPrice, roundPrice }
}