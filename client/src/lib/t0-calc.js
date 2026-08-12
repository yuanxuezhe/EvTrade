/**
 * t0-calc.js — 快速做T 纯函数计算层 (新增于 t0-trade-polish-bundle)
 *
 * 用途：
 *   - 提取 useQuickT0 / useT0Balance 中的零依赖纯函数
 *   - T0Trade.vue 与未来批量做T 页面 (T0OverviewPanel 等) 共用
 *   - 易测试 (无 store / reactive 依赖, 单测覆盖边界)
 *
 * 设计原则：
 *   - 纯函数 (无副作用, 接受入参返结构化返回值)
 *   - 边界值: NaN / 0 / 负数 / null 全部转 0, 不抛
 *   - 返回结构化结果 (`{ok, need, have, gap}` / `{qty, side, error}`) 而非裸 number,
 *     让调用方能用 disabled 态 + tooltip 文案
 *
 * 单一权威源：本文件定义后, useQuickT0 / useT0Balance 内部 import 这些函数,
 * 禁止各自重复实现 roundToLot / 价格映射
 *
 * change t0-trade-polish-bundle (1 commit scope: lib/t0-calc 抽纯函数层)
 */

/** 默认手 (整百股) */
export const DEFAULT_LOT_SIZE = 100

/** A 股买方向 (broker protocol) */
export const ORDER_TYPE_BUY = '23'
/** A 股卖方向 (broker protocol) */
export const ORDER_TYPE_SELL = '24'

/** 价格类型 → broker priceTypeCode (与 useQuickT0.PRICE_TYPE_OPTIONS 对齐) */
const PRICE_TYPE_CODE_MAP = {
  last: 11,     // 限价-最新价
  market: 44,   // 市价
  bidask: 11,   // 卖1买1 (后端按 11 撮合, magic value 不同, 此处保持 11 与原实现一致)
}


/**
 * 整手取整 (向 -∞ 方向 floor, 金融语义)
 *   250 → 200, 150 → 100, -150 → -200, 99 → 0, -50 → 0
 *   0 / NaN / null → 0
 *
 * 真 floor (向 -∞): 用 Math.floor(n / lot) * lot, 不取 abs 再 floor 再 neg
 *   (后者对负数会"截断"而非"向下", -150 会得 -100 而非 -200)
 *
 * @param {number} vol — 任意股数
 * @param {number} [lotSize=100] — 手数 (默认 100)
 * @returns {number} — 整手后的股数
 */
export function roundToLot(vol, lotSize = DEFAULT_LOT_SIZE) {
  const n = Number(vol)
  if (!Number.isFinite(n) || n === 0) return 0
  const lot = Number(lotSize) || DEFAULT_LOT_SIZE
  if (Math.abs(n) < lot) return 0  // < 1 手归零 (避免 -0 符号零)
  return Math.floor(n / lot) * lot
}


/**
 * 配平量计算 (M-008 v3 + t0-balance 合并语义):
 *   need = 当前持仓 + 今日净买入 (今日买 - 今日卖)
 *     正数 → 需买入 (建仓/补仓)
 *     负数 → 需卖出 (锁仓)
 *     0   → 已平仓, error 提示
 *
 * @param {Object} params
 * @param {number} params.vol — 当前持仓 (vol 或 avl_vol)
 * @param {number} params.todayBuy — 今日累计买入股数
 * @param {number} params.todaySell — 今日累计卖出股数
 * @returns {{qty: number, side: ('buy'|'sell'|null), error: (string|null)}}
 */
export function calcBalanceQty({ vol = 0, todayBuy = 0, todaySell = 0 } = {}) {
  const v = Number(vol) || 0
  const buy = Number(todayBuy) || 0
  const sell = Number(todaySell) || 0
  const net = buy - sell
  const need = v + net
  if (need === 0) {
    return { qty: 0, side: null, error: '已平仓, 无需配平' }
  }
  return {
    qty: roundToLot(Math.abs(need)),
    side: need > 0 ? 'buy' : 'sell',
    error: null,
  }
}


/**
 * 资金够不够 (买方向)
 *   - 非 buy 方向: 直接返 `{ok: true, need: 0, have: cash, gap: 0}` (卖方向不需资金)
 *   - qty / price 无效 (≤0 / NaN): 返 `{ok: true, ...}` (不阻塞, 视为不需要资金)
 *   - buy 且 need <= cash: ok
 *   - buy 且 need >  cash: not ok + gap
 *
 * 与 broker PriceCalc.compute_required 一致: need = qty * price
 *
 * @param {Object} params
 * @param {('buy'|'sell')} params.side
 * @param {number} params.qty — 委托股数
 * @param {number} params.price — 委托价 (市价时传 lastPrice)
 * @param {number} params.cash — 可用资金 (asset.cash)
 * @returns {{ok: boolean, need: number, have: number, gap: number}}
 */
export function calcInsufficientCash({ side, qty = 0, price = 0, cash = 0 } = {}) {
  const safeCash = Number(cash) || 0
  if (side !== 'buy') {
    return { ok: true, need: 0, have: safeCash, gap: 0 }
  }
  const q = Number(qty) || 0
  const p = Number(price) || 0
  if (q <= 0 || p <= 0) {
    return { ok: true, need: 0, have: safeCash, gap: 0 }
  }
  const need = q * p
  const gap = Math.max(0, need - safeCash)
  return { ok: need <= safeCash, need, have: safeCash, gap }
}


/**
 * 持仓够不够 (卖方向)
 *   - 非 sell 方向: 直接返 ok
 *   - qty 无效: ok (不阻塞)
 *   - sell 且 qty <= currentVolume: ok
 *   - sell 且 qty >  currentVolume: not ok + gap
 *
 * @param {Object} params
 * @param {('buy'|'sell')} params.side
 * @param {number} params.qty — 委托股数
 * @param {number} params.currentVolume — 当前可用持仓 (avl_vol 优先, vol 兜底)
 * @returns {{ok: boolean, need: number, have: number, gap: number}}
 */
export function calcInsufficientPosition({ side, qty = 0, currentVolume = 0 } = {}) {
  const safeVol = Number(currentVolume) || 0
  if (side !== 'sell') {
    return { ok: true, need: 0, have: safeVol, gap: 0 }
  }
  const q = Number(qty) || 0
  if (q <= 0) {
    return { ok: true, need: 0, have: safeVol, gap: 0 }
  }
  const gap = Math.max(0, q - safeVol)
  return { ok: q <= safeVol, need: q, have: safeVol, gap }
}


/**
 * 价格类型字符串 → broker priceTypeCode
 *   未知值: 兜底返回 11 (与 useT0OrderSubmit 同)
 *
 * @param {('last'|'market'|'bidask'|string)} priceType
 * @returns {number} broker priceTypeCode
 */
export function resolvePriceTypeCode(priceType) {
  return PRICE_TYPE_CODE_MAP[priceType] ?? 11
}


// ============== v54 quick-t0-revamp: 做T盈亏/敞口/期初配额/做T收益率/配平对手盘价 ==============
//
// 背景: 用户反馈 T0Trade.vue 4 类问题 — 做T盈亏口径错位 / 配平价格档错位 / 可买可卖基数错 / 价格 2 位精度硬卡
// 落点: 本文件新增 5 纯函数, T0Trade.vue 主表重做时调用, 不依赖 store
// change: 2026-07-16-quick-t0-revamp, REQ-FE-220


/**
 * 做T盈亏（trader 直觉口径, 不含成本基准/费用）
 * = SUM(卖出成交 vol*price) - SUM(买入成交 vol*price)
 * = stats.today_sell_amount - stats.today_buy_amount
 *
 * 与 v6 realized_pnl (基于 cost_basis + 费用) **语义不同**:
 *   - t0 PnL: 纯流量差 (trader 直觉)
 *   - realized_pnl: 持仓视角已实现 (含成本基准 + 交易费用)
 * 两者共存, 前端用 t0 PnL 做"做T盈亏"列, 后端 realized_pnl 仍按 v6 给 Dashboard/Trade 用
 *
 * @param {{today_buy_amount?: number, today_sell_amount?: number}} stats — t0-stats/{code} 单条
 * @returns {number} 做T盈亏 (正数=盈利, 负数=亏损, 0/NaN/缺字段 → 0)
 */
export function calcT0Pnl(stats) {
  if (!stats || typeof stats !== 'object') return 0
  const buy = Number(stats.today_buy_amount) || 0
  const sell = Number(stats.today_sell_amount) || 0
  return sell - buy
}


/**
 * 当前敞口（持仓视角）
 * = 期初持仓 (last_vol) + 今日净买 (today_buy - today_sell)
 *   > 0 → 多头敞口 (已超期初, 需卖)
 *   < 0 → 空头敞口 (已卖超期初, 需买)
 *   = 0 → 已配平
 *
 * @param {{last_vol?: number}} row — 持仓行 (含 last_vol)
 * @param {{today_buy_volume?: number, today_sell_volume?: number}} stats
 * @returns {number} 敞口 (正数=多, 负数=空)
 */
export function calcExposure(row, stats) {
  const lastVol = Number(row?.last_vol) || 0
  const buyVol = Number(stats?.today_buy_volume) || 0
  const sellVol = Number(stats?.today_sell_volume) || 0
  return lastVol + (buyVol - sellVol)
}


/**
 * 期初配额 — 可买/可卖, 按 last_vol 递减已成交
 *   maxBuyable  = max(0, last_vol - today_buy_volume)
 *   maxSellable = max(0, last_vol - today_sell_volume)
 *
 * 与 useT0Quota.rowQuota (cash/avl_vol) 语义不同:
 *   - 这里是做T 视角, 受限于期初持仓
 *   - useT0Quota 是账户视角, 受限于资金/可用持仓
 *
 * @param {{last_vol?: number}} row
 * @param {{today_buy_volume?: number, today_sell_volume?: number}} stats
 * @returns {{maxBuyable: number, maxSellable: number}}
 */
export function calcInitialQuota(row, stats) {
  const lastVol = Number(row?.last_vol) || 0
  const buyVol = Number(stats?.today_buy_volume) || 0
  const sellVol = Number(stats?.today_sell_volume) || 0
  return {
    maxBuyable: Math.max(0, lastVol - buyVol),
    maxSellable: Math.max(0, lastVol - sellVol),
  }
}


/**
 * 做T收益率（小数, 0.005 = 0.5%）
 * = calcT0Pnl(stats) / (last_vol * cost_price)
 *
 * 边界: last_vol ≤ 0 或 cost_price ≤ 0 或非有限数 → 0 (避免除零)
 *
 * @param {{last_vol?: number, cost_price?: number}} row
 * @param {Object} stats — t0-stats 单条 (含 today_buy_amount, today_sell_amount)
 * @returns {number} 收益率小数
 */
export function calcT0ReturnRate(row, stats) {
  const lastVol = Number(row?.last_vol) || 0
  const cost = Number(row?.cost_price) || 0
  if (lastVol <= 0 || cost <= 0) return 0
  const denom = lastVol * cost
  if (!Number.isFinite(denom) || denom <= 0) return 0
  const pnl = calcT0Pnl(stats)
  if (!Number.isFinite(pnl)) return 0
  return pnl / denom
}


/**
 * 配平对手盘价（独立于 quick 价格档）
 * = buy 敞口 → ask_prices[0] (卖1价)
 * = sell 敞口 → bid_prices[0] (买1价)
 *
 * 取不到 (ask/bid 为空/无效) → fallback last_price, 返回 fallback=true 让 UI 提示
 * 都没有 → price=0, 让 useT0OrderSubmit 走 broker priceTypeCode 撮合 (priceTypeCode=11)
 *
 * @param {{stock_code?: string}} row
 * @param {('buy'|'sell')} side — 配平方向 (买=补仓, 卖=锁仓)
 * @param {Object|null|undefined} quote — quote store 单条 {last_price, ask_prices, bid_prices, ...}
 * @returns {{price: number, fallback: boolean}}
 */
export function resolveBalancePrice(row, side, quote) {
  const q = quote || {}
  const lastPrice = Number(q.last_price) || 0

  if (side === 'buy') {
    // 买敞口 → 卖1价
    const ask1 = Number(q.ask_prices?.[0]) || 0
    if (ask1 > 0 && Number.isFinite(ask1)) return { price: ask1, fallback: false }
    if (lastPrice > 0) return { price: lastPrice, fallback: true }
    return { price: 0, fallback: true }
  }

  if (side === 'sell') {
    // 卖敞口 → 买1价
    const bid1 = Number(q.bid_prices?.[0]) || 0
    if (bid1 > 0 && Number.isFinite(bid1)) return { price: bid1, fallback: false }
    if (lastPrice > 0) return { price: lastPrice, fallback: true }
    return { price: 0, fallback: true }
  }

  return { price: lastPrice, fallback: false }
}


// ============== 当日盈亏 (昨收基准, broker 口径) ==============
//
// 公式:
//   当日盈亏 = (当前持仓 × 最新价 + 今日卖出额)
//             − (期初持仓 × 昨收价 + 今日买入额)
//             − 当日费用
//
// 含义: 对比"期初持仓按昨收定价"的基准市值, 当前持仓市值 + 今日卖出回笼现金,
// 减去今日买入投入现金与当日费用, 得到该标的当日真实盈亏 (含已实现 + 未实现).
// 与 calcT0Pnl (纯流量差, 不含成本基准/费用) 语义不同, 与后端 realized_pnl
// (成本基准已实现) 也不同 — 三者并存, 各自服务于不同展示口径.

/**
 * 当日盈亏 (昨收基准, 含当日费用)
 *
 * @param {Object} params
 * @param {number} params.vol          — 当前持仓股数
 * @param {number} [params.last_price] — 最新价 (缺 → 返 null, 让 UI 显示 '—')
 * @param {number} params.last_vol     — 期初持仓股数
 * @param {number} [params.prev_close] — 昨收价 (缺 → 返 null)
 * @param {number} params.buy_amount   — 今日买入成交额 (后端 t0-exposure 聚合)
 * @param {number} params.sell_amount  — 今日卖出成交额
 * @param {number} params.day_fee      — 当日费用 (买佣金+卖佣金+印花税, 后端按费率算)
 * @returns {number|null} 当日盈亏; 行情缺失 (last_price/prev_close 任一无效) → null
 */
export function calcDayPnl({
  vol = 0,
  last_price = null,
  last_vol = 0,
  prev_close = null,
  buy_amount = 0,
  sell_amount = 0,
  day_fee = 0,
} = {}) {
  const lp = Number(last_price)
  const pc = Number(prev_close)
  if (last_price == null || prev_close == null || !Number.isFinite(lp) || !Number.isFinite(pc)) return null
  const cur = Number(vol) || 0
  const lv = Number(last_vol) || 0
  const buy = Number(buy_amount) || 0
  const sell = Number(sell_amount) || 0
  const fee = Number(day_fee) || 0
  return (cur * lp + sell) - (lv * pc + buy) - fee
}


// ============== 浮动盈亏 (扣费, 对齐当日盈亏口径) ==============
//
// change floating-pnl-fee (2026-08-12): 浮动盈亏从裸价差 (现价−成本)×量 改为扣费版。
// 费用 = 当日盈亏的 day_fee (后端 t0-exposure 按**当日实际买卖成交金额**聚合:
//   买佣金(今日买入额) + 卖佣金(今日卖出额) + 印花税, aggregators.py:123)。
// 前端不做二次费率逻辑 (REQ-FE-533) — 直接扣后端 day_fee, 与当日盈亏费用完全一致,
// 避免浮动盈亏按整仓名义额自算佣金导致比当日盈亏多一倍 (159530.SZ 实测)。

/**
 * 浮动盈亏（扣费版, 对齐当日盈亏费用）
 *
 * 公式:
 *   浮动盈亏 = (现价 − 成本) × 量 − 当日费用 day_fee
 *
 * day_fee 由后端按当日实际买卖成交金额计算 (t0-exposure 聚合), 与当日盈亏同一费用值;
 * 无 day_fee (未拉取/当日无成交) → 0, 退化裸价差, 不抛。
 *
 * @param {Object} params
 * @param {number|null} params.price — 最新现价 (null → 返 null, UI 显示 '—')
 * @param {number} params.cost       — 持仓成本价 (cost_price, scale 精度)
 * @param {number} params.vol        — 持仓量 (vol)
 * @param {number} [params.day_fee]  — 当日费用 (后端 t0-exposure day_fee, 默认 0)
 * @returns {number|null} 扣费后浮动盈亏 (round 2); 行情缺失 → null; vol=0 → 0
 */
export function calcFloatingPnl({ price, cost, vol, day_fee = 0 } = {}) {
  const p = Number(price)
  const c = Number(cost) || 0
  const v = Number(vol) || 0
  if (price == null || !Number.isFinite(p)) return null
  if (v === 0) return 0
  const gross = (p - c) * v
  const fee = Number(day_fee) || 0
  return Math.round((gross - fee) * 100) / 100
}
