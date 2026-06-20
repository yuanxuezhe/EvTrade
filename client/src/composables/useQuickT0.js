/**
 * useQuickT0.js — 快速做T 纯函数工具集 (M-008)
 *
 * 用户需求: "按当前持仓数量的百分比" + 价格 3 档 + 仓位 4 档.
 *
 * 设计原则:
 *   - 纯函数 (无副作用, 无 store 依赖)
 *   - 易测试 (vitest 8 个用例覆盖)
 *   - 易复用 (T0Trade.vue 行内按钮 / 未来策略页都用)
 *
 * 仓位计算公式 (用户拍板):
 *   qty = round(vol × pct / 100 / 100) × 100   // 整百股 (A股最小手)
 *
 * 价格档位 (3 档):
 *   - 'last'    最新价 (默认)
 *   - 'market'  市价 (price=0 让 broker 端按市价)
 *   - 'bidask'  卖1买1 (优先 ask1, 退化为最新价)
 *
 * 价格类型码 (后端 PriceType 枚举, server/models/orm.py):
 *   - 11 限价  (LIMIT)
 *   - 12 即成剩撤 (MARKET 部分券商)
 *   - 14 对手方最优 (bidask 走 11 + ask1 价格)
 *   - 44 市价 (xtquant 专用)
 */
import { ElMessage } from 'element-plus'

// 仓位 4 档 (用户拍板)
export const PCT_OPTIONS = [25, 50, 75, 100]

// 价格 3 档 (用户拍板)
export const PRICE_TYPE_OPTIONS = [
  { value: 'last',   label: '最新价', code: 11 },
  { value: 'market', label: '市价',   code: 44 },
  { value: 'bidask', label: '卖1买1', code: 11 },  // bidask 限价 + ask1 价格
]

// localStorage 键
const LS_KEY_PCT = 't0.quickPct'
const LS_KEY_PRICE_TYPE = 't0.quickPriceType'

// 默认值
export const DEFAULT_PCT = 50
export const DEFAULT_PRICE_TYPE = 'last'


/**
 * 整百股取整 (向下取整, 不超用户预期).
 *
 * 金融语义: A 股最小手 100 股, 委托零碎股 (如 250) 会被券商拒.
 * 向下取整 (floor) 保证不超用户设置的百分比, 避免"我买 25% 却买了 30%".
 *
 *   roundToLot(123) = 100
 *   roundToLot(250) = 200   // 250 不可委托, 退到 200
 *   roundToLot(1000)= 1000
 *   roundToLot(0)   = 0
 *   roundToLot(-150)= -200  // 卖空时向下 (绝对值更大)
 */
export function roundToLot(vol, lot = 100) {
  if (!Number.isFinite(vol)) return 0
  // 金融 floor: 统一向下取整 (向 -∞ 方向), 不论正负
  //   150  → 100 (不足 1 手, 退到 0 手)
  //   -150 → -200 (卖出更多, 绝对值更大, 保守)
  return Math.floor(vol / lot) * lot
}


/**
 * 计算快买数量 = vol × pct / 100 (整百股).
 *   vol=1000, pct=50 → 500
 *   vol=1000, pct=25 → 250 → roundToLot → 200 (优先满足"≥pct 比例"的最近整百)
 *
 * 注: 严格按用户"按当前持仓数量百分比"语义, 不超额.
 */
export function calcBuyQty(row, pct = 50) {
  if (!row || !Number.isFinite(row.vol) || row.vol <= 0) return 0
  if (!Number.isFinite(pct) || pct <= 0) return 0
  return roundToLot(row.vol * pct / 100)
}


/**
 * 计算快卖数量 (同 calcBuyQty 镜像).
 */
export function calcSellQty(row, pct = 50) {
  return calcBuyQty(row, pct)
}


/**
 * 计算快买数量 (按 4 档 25/50/75/100).
 * 选 N% → 买 (vol × N/100) 整百股.
 */
export function calcQuickQty(vol, pct) {
  if (!Number.isFinite(vol) || vol <= 0) return 0
  if (!Number.isFinite(pct) || pct <= 0) return 0
  return roundToLot(vol * pct / 100)
}


/**
 * 解析价格 (3 档).
 *   - 'last'    → quoteStore.getLastPrice(code)
 *   - 'market'  → 0  (broker 端按市价处理)
 *   - 'bidask'  → quoteStore.getQuote(code).ask1 ?? getLastPrice(code)
 *
 * 返回 { price, priceTypeCode, label }.
 */
export function resolvePrice(priceType, code, quoteStore) {
  const opt = PRICE_TYPE_OPTIONS.find((o) => o.value === priceType)
  if (!opt) {
    return { price: 0, priceTypeCode: 11, label: '限价' }
  }

  if (priceType === 'market') {
    return { price: 0, priceTypeCode: opt.code, label: opt.label }
  }

  // last / bidask 都用最新价 (bidask 优先 ask1, 没有就退 last)
  const last = quoteStore?.getLastPrice?.(code) ?? 0
  let price = last
  if (priceType === 'bidask') {
    const ask = quoteStore?.getQuote?.(code)?.ask1 ?? quoteStore?.getField?.(code, 'ask1')
    if (Number.isFinite(ask) && ask > 0) price = ask
  }
  return { price, priceTypeCode: opt.code, label: opt.label }
}


/**
 * 检查 0 持仓买按钮是否应禁用 (用户拍板 A).
 * 卖按钮: 永远不因 0 持仓禁用 (但提交时若 qty=0 仍会拦截).
 */
export function isBuyDisabled(row) {
  if (!row) return true
  if (!Number.isFinite(row.vol) || row.vol <= 0) return true
  return false
}


/**
 * 校验快买快卖提交 (返回 null = OK, 字符串 = 错误信息).
 * 错误时调用方应 ElMessage.warning(err) 并 return.
 */
export function validateQuick(row, qty, side /* 'buy' | 'sell' */) {
  if (!row || !row.stock_code) return '无效的持仓行'
  if (side === 'buy' && isBuyDisabled(row)) {
    return '0 持仓无法按比例买, 请用「固定数量」模式建仓'
  }
  if (!Number.isFinite(qty) || qty === 0) {
    return side === 'buy'
      ? '仓位比例折算 0 股, 调大比例或先建仓'
      : '持仓数量为 0, 无法卖出'
  }
  return null
}


/**
 * localStorage 持久化 (default 50 + 'last').
 */
export function loadQuickDefaults() {
  let pct = DEFAULT_PCT
  let priceType = DEFAULT_PRICE_TYPE
  try {
    const p = localStorage.getItem(LS_KEY_PCT)
    if (p && PCT_OPTIONS.includes(Number(p))) pct = Number(p)
    const pt = localStorage.getItem(LS_KEY_PRICE_TYPE)
    if (pt && PRICE_TYPE_OPTIONS.find((o) => o.value === pt)) priceType = pt
  } catch (_) {
    // localStorage 可能被禁用 (隐私模式) — 静默降级
  }
  return { pct, priceType }
}


export function saveQuickDefaults(pct, priceType) {
  try {
    localStorage.setItem(LS_KEY_PCT, String(pct))
    localStorage.setItem(LS_KEY_PRICE_TYPE, String(priceType))
  } catch (_) {
    // 静默失败, 不影响主流程
  }
}


/**
 * 一站式: 给定持仓行 + 仓位 + 价格档, 返回 { qty, price, priceTypeCode, error }.
 * T0Trade.vue 行内 [买 N%] 按钮直接调这个, 然后传 submitOrder.
 */
export function buildQuickOrder(row, side, pct, priceType, quoteStore) {
  const qty = calcQuickQty(Number(row?.vol) || 0, pct)
  const err = validateQuick(row, qty, side)
  if (err) return { qty: 0, price: 0, priceTypeCode: 11, error: err }
  const { price, priceTypeCode } = resolvePrice(priceType, row.stock_code, quoteStore)
  if (!Number.isFinite(price) || price <= 0) {
    return { qty, price: 0, priceTypeCode, error: `${row.stock_code} 无行情, 请稍后再试` }
  }
  return { qty, price, priceTypeCode, error: null }
}
