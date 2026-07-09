import { defineStore } from 'pinia'
import { reactive, computed } from 'vue'
import { http } from '../api'  // axios 实例 + Bearer interceptor (api/index.js:12-24)

/**
 * 行情缓存 + 订阅管理（v15 2026-07-09 quote-snapshot-subscribe）
 *
 * 数据源：
 *   1. WS push 帧: ws_dispatch._onQuote → update({stock_code, last_price, snapshot, fields, body})
 *   2. WS subscribe_ack 帧: ws_dispatch._onSnapshot → applySnapshots({[code]: snapshot})
 *   3. REST 一次性拉取: fetchSnapshots([codes]) → applySnapshots(...)
 *
 * 字段索引（31 字段，hqserver 已经按 |\n 拆分 + QMT publisher format_quote 顺序）：
 *   [ 0] stock_code
 *   [ 1] datetime (yyyyMMddHHmmss.sss)
 *   [ 2] 最新价
 *   [ 3] 开盘价
 *   [ 4] 最高价
 *   [ 5] 最低价
 *   [ 6] 昨收
 *   [ 7] 成交量
 *   [ 8] 成交额
 *   [ 9] openInt (持仓量, 暂未入库)
 *   [10] transactionNum (成交笔数, 暂未入库)
 *   [11..15] 卖1价..卖5价
 *   [16..20] 买1价..买5价
 *   [21..25] 卖1量..卖5量
 *   [26..30] 买1量..买5量
 *
 * 兼容旧 layout（30 字段 + 1 填充）：fields 长度可能是 30 或 31。
 */
export const FIELD = {
  LAST: 2, OPEN: 3, HIGH: 4, LOW: 5, PREV_CLOSE: 6,
  VOLUME: 7, AMOUNT: 8,
  ASK_PRICE: 11,  // [11..15]  卖1价..卖5价（递增）
  BID_PRICE: 16,  // [16..20]  买1价..买5价（递减）
  ASK_VOL: 21,    // [21..25]  卖1量..卖5量
  BID_VOL: 26     // [26..30]  买1量..买5量
}

export const useQuoteStore = defineStore('quote', () => {
  // byCode: stock_code -> { last_price, open_price, high_price, low_price, prev_close,
  //                        volume, amount, fields, body, ts }
  const byCode = reactive(new Map())
  // 2026-07-09: 维护当前已订阅的 code 集合（防止重复 subscribe + 退出页面时 unsubscribe）
  const subscribedSet = reactive(new Set())

  /**
   * 接收 ws push 帧（quote_consumer → ws_manager.broadcast 来的 data）
   * payload 形如 { stock_code, last_price, snapshot, fields, body }
   * - snapshot: 后端 QuoteSnapshot ORM dict（22 字段，已数值化）
   * - fields/body: 原始 31 字段 + GBK body（兼容 QuotePanel 的旧 fields[] 解析）
   */
  function update(payload) {
    if (!payload || !payload.stock_code) return
    const cur = byCode.get(payload.stock_code) || {}
    const next = {
      ...cur,
      stock_code: payload.stock_code,
      last_price: payload.last_price != null ? Number(payload.last_price) : (cur.last_price ?? null),
      fields: payload.fields || cur.fields || [],
      body: payload.body ?? cur.body ?? '',
      ts: payload.ts || Date.now(),
    }
    // 优先用 snapshot dict（已数值化、字段命名稳定）覆盖
    if (payload.snapshot && typeof payload.snapshot === 'object') {
      const s = payload.snapshot
      if (s.open_price != null) next.open_price = Number(s.open_price)
      if (s.high_price != null) next.high_price = Number(s.high_price)
      if (s.low_price != null) next.low_price = Number(s.low_price)
      if (s.prev_close != null) next.prev_close = Number(s.prev_close)
      if (s.volume != null) next.volume = Number(s.volume)
      if (s.amount != null) next.amount = Number(s.amount)
      if (s.ask1_price != null) {
        next.ask_prices = [s.ask1_price, s.ask2_price, s.ask3_price, s.ask4_price, s.ask5_price].map(Number)
      }
      if (s.bid1_price != null) {
        next.bid_prices = [s.bid1_price, s.bid2_price, s.bid3_price, s.bid4_price, s.bid5_price].map(Number)
      }
      if (s.ask1_vol != null) {
        next.ask_vols = [s.ask1_vol, s.ask2_vol, s.ask3_vol, s.ask4_vol, s.ask5_vol].map(Number)
      }
      if (s.bid1_vol != null) {
        next.bid_vols = [s.bid1_vol, s.bid2_vol, s.bid3_vol, s.bid4_vol, s.bid5_vol].map(Number)
      }
    }
    byCode.set(payload.stock_code, next)
  }

  /**
   * 接收 subscribe_ack 或 REST /api/quote/snapshots 的批量数据
   * snapMap: { [stock_code]: snapshot_dict }
   */
  function applySnapshots(snapMap) {
    if (!snapMap || typeof snapMap !== 'object') return
    for (const [code, snap] of Object.entries(snapMap)) {
      if (!snap) continue
      // 用 snapshot dict 当 update payload: 复用 update() 路径
      update({ stock_code: code, last_price: snap.last_price, snapshot: snap, ts: snap.ts })
    }
  }

  /**
   * 2026-07-09: 批量订阅（Q1B 一波）
   * 流程：
   *   1) 本地标记 subscribed（防止重复发）
   *   2) 调 ws_dispatch.subscribe(codes)（发到后端）
   *   3) 后端返 subscribe_ack（含最新 snapshots）→ 走 ws_dispatch._onSnapshot
   *   4) REST /api/quote/snapshots 立即拉一次最新值（避免 ws 没 tick 时首屏空白）
   *
   * 新订阅的 codes 自动取消订阅（与后端 ws_manager.subscribe 幂等一致）。
   */
  async function subscribe(codes) {
    if (!Array.isArray(codes) || codes.length === 0) return
    const newCodes = codes.filter(c => c && !subscribedSet.has(c))
    if (newCodes.length === 0) return
    // 标记
    newCodes.forEach(c => subscribedSet.add(c))
    // 1) REST 拉最新
    try {
      // 2026-07-09 fix: api 是业务方法对象(无 .post), 必须用 http (axios 实例) 走 Bearer interceptor
      const { data } = await http.post('/quote/snapshots', { stock_codes: newCodes })
      if (data && data.snapshots) {
        applySnapshots(data.snapshots)
      }
    } catch (e) {
      console.warn('[quoteStore] fetchSnapshots failed:', e?.message)
    }
    // 2) WS subscribe
    try {
      const { subscribe: wsSubscribe } = await import('./ws_dispatch')
      wsSubscribe(newCodes)
    } catch (e) {
      console.warn('[quoteStore] ws subscribe failed:', e?.message)
    }
  }

  /**
   * 取消订阅（页面卸载时调用，避免幽灵订阅）
   */
  function unsubscribe(codes) {
    if (!Array.isArray(codes) || codes.length === 0) return
    const removed = codes.filter(c => subscribedSet.has(c))
    if (removed.length === 0) return
    removed.forEach(c => subscribedSet.delete(c))
    import('./ws_dispatch').then(({ unsubscribe: wsUnsubscribe }) => {
      wsUnsubscribe(removed)
    }).catch(e => console.warn('[quoteStore] ws unsubscribe failed:', e?.message))
  }

  function get(code) {
    return byCode.get(code) || null
  }
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

  // 涨跌幅（%），优先用 snapshot 字段（prev_close + last_price）
  const getChangePct = (code) => {
    const q = byCode.get(code)
    if (!q) return null
    const last = q.last_price
    const prev = q.prev_close != null ? q.prev_close : (q.fields ? Number(q.fields[FIELD.PREV_CLOSE]) : null)
    if (last == null || prev == null || !Number.isFinite(last) || !Number.isFinite(prev) || prev === 0) return null
    return ((last - prev) / prev) * 100
  }

  // 2026-07-09: 返回 5 档买卖价 (兼容旧 fields 索引访问)
  function getDepth(code) {
    const q = byCode.get(code)
    if (!q) return null
    if (q.ask_prices && q.bid_prices) {
      return {
        asks: q.ask_prices.map((p, i) => ({ price: p, vol: q.ask_vols?.[i] ?? 0 })),
        bids: q.bid_prices.map((p, i) => ({ price: p, vol: q.bid_vols?.[i] ?? 0 })),
      }
    }
    // 兜底: 从 fields 解析
    if (q.fields) {
      const askP = [], bidP = [], askV = [], bidV = []
      for (let i = 0; i < 5; i++) {
        askP.push(Number(q.fields[FIELD.ASK_PRICE + i] ?? 0))
        bidP.push(Number(q.fields[FIELD.BID_PRICE + i] ?? 0))
        askV.push(Number(q.fields[FIELD.ASK_VOL + i] ?? 0))
        bidV.push(Number(q.fields[FIELD.BID_VOL + i] ?? 0))
      }
      return {
        asks: askP.map((p, i) => ({ price: p, vol: askV[i] })),
        bids: bidP.map((p, i) => ({ price: p, vol: bidV[i] })),
      }
    }
    return null
  }

  const codes = computed(() => Array.from(byCode.keys()))

  return {
    byCode, subscribedSet,
    update, applySnapshots, subscribe, unsubscribe,
    get, getQuote, getLastPrice, getField, getChangePct, getDepth,
    codes, FIELD,
  }
})