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
