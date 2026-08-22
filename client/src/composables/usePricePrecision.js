/**
 * usePricePrecision composable — 价格精度统一入口 + 顶层 formatPrice
 *
 * 设计:
 * - 输入 stockCode (ref 或 string), 返回响应式的 precision 数值 (0~6)
 * - 走 stocks store 的 stockScale() helper, 读 cache, cache miss 兜底 2
 * - Vue 组件内 :precision="precision" 即可让 el-input-number 按 scale round
 *
 * formatPrice 为顶层 export (named import `import { formatPrice }` 可直接使用).
 *
 * 用法 A (单值 formatPrice, 推荐用于表格列):
 *   import { formatPrice } from '../composables/usePricePrecision'
 *   <span>{{ formatPrice(row.price, row.stock_code) }}</span>
 *
 * 用法 B (响应式 precision + stktype, 推荐用于输入框):
 *   const { precision, stktype, formatPrice, roundPrice } = usePricePrecision(() => stockCode.value)
 *   <el-input-number :precision="precision" />
 */
import { computed, unref } from 'vue'
import { useStocksStore } from '../stores/stocks'

/**
 * 顶层 formatPrice — 按 stockCode 精度四舍五入显示价格 (无需 composable instance)
 * 内部直接读 stocksStore, 等价于 factory 内 formatPrice 但可被 named import.
 *
 * @param {number|string|null|undefined} price
 * @param {string|null|undefined} stockCode - 证券代码; 不传则走默认 scale=2
 * @returns {string} 格式化后的价格字符串 (e.g. "10.85")
 */
export function formatPrice(price, stockCode) {
  if (price === null || price === undefined || price === '') return ''
  const n = Number(price)
  if (!Number.isFinite(n)) return ''
  const stocksStore = useStocksStore()
  const p = stockCode ? stocksStore.stockScale(stockCode) : 2
  return n.toFixed(p)
}

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
   * 注: 顶层 formatPrice 已抽出, 此处保留作 backward-compat (供 factory 内部使用)
   */
  function instanceFormatPrice(price, stockCode) {
    if (price === null || price === undefined || price === '') return ''
    const n = Number(price)
    if (!Number.isFinite(n)) return ''
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

  return { precision, stktype, formatPrice: instanceFormatPrice, roundPrice }
}
