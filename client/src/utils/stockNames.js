/**
 * 证券名称查表 util（v32 优化：name 不返后端，前端查 stocks cache 补）
 *
 * 数据流:
 *   后端 (holdings / orders / trades API) 不再返回证券名称
 *   前端通过 stock_code 查 stocks store 缓存补 name
 *   查不到 → 显式返回 null（让调用方决定占位，默认 '—'）
 *
 * 设计要点:
 *   - stockName(code) 是唯一入口，所有表格列都走它
 *   - 不在 util 内做 fallback 占位字符串 — 显示层决定
 *   - 缓存未加载 (cacheLoaded = false) 也返回 null，不阻塞 render
 */
import { useStocksStore } from '../stores/stocks'

/**
 * 按 stock_code 查证券名称（从 stocks store 全量缓存）
 * @param {string} code - stock_code
 * @returns {string|null} name 或 null（查不到 / 缓存未加载）
 */
export function stockName(code) {
  if (!code) return null
  const store = useStocksStore()
  if (!store || !store.cacheLoaded) return null
  const found = store.cache.find((s) => s.stock_code === code)
  return found?.stock_name || null
}

/**
 * stockName + 默认占位字符串
 * @param {string} code - stock_code
 * @param {string} fallback - 占位字符串，默认 '—'
 * @returns {string} name 或 fallback
 */
export function stockNameOrDash(code, fallback = '—') {
  return stockName(code) || fallback
}
