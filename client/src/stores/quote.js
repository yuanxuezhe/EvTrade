import { defineStore } from 'pinia'
import { reactive, computed } from 'vue'

/**
 * 行情缓存：stock_code -> {
 *   last_price, fields: string[], body, ts
 * }
 *
 * fields 索引（30 字段布局，用户文档版本）：
 *   [ 0] stock_code
 *   [ 1] datetime (yyyyMMddHHmmss.sss)
 *   [ 2] 最新价
 *   [ 3] 开盘价
 *   [ 4] 最高价
 *   [ 5] 最低价
 *   [ 6] 昨收
 *   [ 7] 成交量
 *   [ 8] 成交额
 *   [ 9..13] 卖1价..卖5价
 *   [14..18] 买1价..买5价
 *   [19..23] 卖1量..卖5量
 *   [24..28] 买1量..买5量
 *   [29] 末尾填充
 *
 * 注：broker 实际可能发 31 字段（多 1 个尾部填充），字段含义按前 30 个对。
 */

export const FIELD = {
  LAST: 2, OPEN: 3, HIGH: 4, LOW: 5, PREV_CLOSE: 6,
  VOLUME: 7, AMOUNT: 8,
  ASK_PRICE: 9,   // [9..13]
  BID_PRICE: 14,  // [14..18]
  ASK_VOL: 19,    // [19..23]
  BID_VOL: 24     // [24..28]
}

export const useQuoteStore = defineStore('quote', () => {
  const byCode = reactive(new Map())

  function update(payload) {
    if (!payload || !payload.stock_code) return
    const cur = byCode.get(payload.stock_code) || {}
    byCode.set(payload.stock_code, {
      ...cur,
      stock_code: payload.stock_code,
      last_price: payload.last_price != null ? Number(payload.last_price) : (cur.last_price ?? null),
      fields: payload.fields || cur.fields || [],
      body: payload.body ?? cur.body ?? '',
      ts: payload.ts || Date.now()
    })
  }

  function get(code) {
    return byCode.get(code) || null
  }
  // alias for get — used by Holdings.vue / QuotePanel.vue
  const getQuote = (code) => get(code)

  function getLastPrice(code) {
    const q = byCode.get(code)
    return q && q.last_price != null ? q.last_price : null
  }

  function getField(code, idx) {
    const q = byCode.get(code)
    if (!q || !q.fields) return null
    return q.fields[idx] ?? null
  }

  // 简单衍生：相对昨收的涨跌幅（%），含正负
  const getChangePct = (code) => {
    const q = byCode.get(code)
    if (!q || !q.fields) return null
    const last = Number(q.fields[FIELD.LAST])
    const prev = Number(q.fields[FIELD.PREV_CLOSE])
    if (!Number.isFinite(last) || !Number.isFinite(prev) || prev === 0) return null
    return ((last - prev) / prev) * 100
  }

  const codes = computed(() => Array.from(byCode.keys()))

  return { byCode, update, get, getQuote, getLastPrice, getField, getChangePct, codes, FIELD }
})