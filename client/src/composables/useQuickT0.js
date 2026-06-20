/**
 * useQuickT0.js — 快速做T 纯函数工具集 (M-008)
 *
 * 用户需求 (M-008 v3 拍板 B+A+A):
 *   - 行内 3 按钮 (买/卖/配平) + 1 详情
 *   - 整行可点 → 打开明细抽屉
 *   - 委托记录走后端 t0_history API
 *
 * 设计原则:
 *   - 纯函数 (无副作用, 无 store 依赖)
 *   - 易测试 (vitest 12+ 用例覆盖)
 *   - 易复用 (T0Trade.vue 行内按钮 / 未来策略页都用)
 *
 * v1/v2 history:
 *   - 2026-06-20 v1: 9 函数 + 8 用例
 *   - 2026-06-20 v2: + 顶置条 + 整行可点
 *   - 2026-06-20 v3: + calcBalanceQty + label 返回 + 无行情检查
 */

/** 4 档仓位百分比 (UI 用) */
export const PCT_OPTIONS = [25, 50, 75, 100]

/** 3 档价格类型 (UI 用) */
export const PRICE_TYPE_OPTIONS = [
  { value: 'last', label: '最新价', priceTypeCode: 11 },
  { value: 'market', label: '市价', priceTypeCode: 44 },
  { value: 'bidask', label: '卖1买1', priceTypeCode: 11 },
]

/** 默认值 */
export const DEFAULT_PCT = 50
export const DEFAULT_PRICE_TYPE = 'last'

/** A 股最小手 (整百股) */
export const LOT_SIZE = 100

/** localStorage key */
const LS_PCT = 't0.quickPct'
const LS_PRICE = 't0.quickPriceType'


// ================== 数量计算 ==================

/**
 * 整百股截断 (金融 floor, 向 -∞ 方向)
 *   250 → 200, 150 → 100, -150 → -200
 *   0/NaN/null → 0
 */
export function roundToLot(vol) {
  const n = Number(vol)
  if (!Number.isFinite(n)) return 0
  return Math.floor(n / LOT_SIZE) * LOT_SIZE
}

/**
 * 按"当前持仓数量 × 百分比" 算买量
 *   calcBuyQty({vol:1000}, 50) = 500
 *   calcBuyQty({vol:0}, 50) = 0 (被 isBuyDisabled 截)
 */
export function calcBuyQty(row, pct) {
  return calcQuickQty(Number(row?.vol) || 0, pct)
}

/**
 * 按"当前持仓数量 × 百分比" 算卖量 (与 calcBuyQty 镜像)
 */
export function calcSellQty(row, pct) {
  return calcQuickQty(Number(row?.vol) || 0, pct)
}

/**
 * 行内快捷版 calcQuickQty(vol, pct) — 直接接受数字
 *   0/无效 → 0
 */
export function calcQuickQty(vol, pct) {
  const v = Number(vol) || 0
  const p = Number(pct)
  if (!Number.isFinite(p)) return 0
  return roundToLot((v * p) / 100)
}


// ================== 价格解析 ==================

/**
 * 3 档价格解析 (调用 quote store)
 *   'last'   → { price: 最新价, priceTypeCode: 11, label }
 *   'market' → { price: 0 (xtquant 内部撮合), priceTypeCode: 44, label }
 *   'bidask' → { price: ask1 (优先于 last), priceTypeCode: 11, label }
 *
 * mock 形式 (用于测试):
 *   {
 *     getLastPrice: (code) => number,
 *     getField: (code, field) => number | null,   // 'ask1' 取卖1
 *   }
 */
export function resolvePrice(priceType, code, quoteStore) {
  const opt = PRICE_TYPE_OPTIONS.find((o) => o.value === priceType) || PRICE_TYPE_OPTIONS[0]
  const last = quoteStore?.getLastPrice?.(code) ?? 0
  if (priceType === 'last') {
    return { price: last, priceTypeCode: opt.priceTypeCode, label: opt.label }
  }
  if (priceType === 'market') {
    return { price: 0, priceTypeCode: opt.priceTypeCode, label: opt.label }  // xtquant 市价不传价
  }
  if (priceType === 'bidask') {
    const ask1 = quoteStore?.getField?.(code, 'ask1') ?? null
    return { price: ask1 || last, priceTypeCode: opt.priceTypeCode, label: opt.label }
  }
  return { price: last, priceTypeCode: 11, label: '最新价' }
}


// ================== 校验 ==================

/**
 * 0 持仓买按钮是否禁用 (用户拍板 A)
 *   vol > 0 → false (不禁)
 *   vol ≤ 0 / 缺 → true (禁)
 */
export function isBuyDisabled(row) {
  const v = Number(row?.vol)
  return !Number.isFinite(v) || v <= 0
}

/**
 * 提交前校验 — 返回 null = OK, 字符串 = 错误信息
 *   - 缺 stock_code → "无效行, 缺少 stock_code"
 *   - 0 持仓买 → "0 持仓无法按比例买"
 *   - 0 持仓卖 → "持仓数量为 0, 无法卖"
 *   - 0 股 → "0 股 无效"
 */
export function validateQuick(row, qty, side /* 'buy' | 'sell' */) {
  const code = row?.stock_code
  if (!code) return '无效行, 缺少 stock_code'
  if (side === 'buy' && isBuyDisabled(row)) {
    return `0 持仓无法按比例买 (${code})`
  }
  if (side === 'sell') {
    const v = Number(row?.vol) || 0
    if (v <= 0) return `${code} 持仓数量为 0, 无法卖`
  }
  if (qty <= 0) {
    return `0 股 无效 (${code})`
  }
  return null
}


// ================== localStorage 持久化 ==================

export function loadQuickDefaults() {
  let pct = DEFAULT_PCT
  let priceType = DEFAULT_PRICE_TYPE
  try {
    const rawPct = localStorage.getItem(LS_PCT)
    const n = Number(rawPct)
    if (Number.isFinite(n) && PCT_OPTIONS.includes(n)) {
      pct = n
    }
    const rawPt = localStorage.getItem(LS_PRICE)
    if (PRICE_TYPE_OPTIONS.some((o) => o.value === rawPt)) {
      priceType = rawPt
    }
  } catch {
    // localStorage 不可用 (SSR / 隐私模式) → 静默回退默认
  }
  return { pct, priceType }
}

export function saveQuickDefaults(pct, priceType) {
  try {
    localStorage.setItem(LS_PCT, String(pct))
    localStorage.setItem(LS_PRICE, String(priceType))
  } catch {
    // 静默失败
  }
}


// ================== 配平 (M-008 v3 新增) ==================

/**
 * 配平量计算 (M-008 v3):
 *   net = 今日买量 - 今日卖量
 *   净持仓 = row.vol
 *   应配平量 = 净持仓 + net
 *     负数 → 需卖出  |  正数 → 需买入
 *
 * 配平用例: 用户早盘买了 100, 下午想锁仓 → 卖 100
 *  返回: { qty, side, error }
 */
export function calcBalanceQty(row, todayBuy = 0, todaySell = 0) {
  const code = row?.stock_code || 'N/A'
  const v = Number(row?.vol) || 0
  const net = (Number(todayBuy) || 0) - (Number(todaySell) || 0)
  const need = v + net
  if (need === 0) {
    return { qty: 0, side: null, error: `${code} 已平仓, 无需配平` }
  }
  const side = need > 0 ? 'buy' : 'sell'
  const qty = roundToLot(Math.abs(need))
  return { qty, side, error: null }
}


// ================== 端到端 buildQuickOrder ==================

/**
 * 行内 [买 50%] [卖 50%] [配平] 按钮调用
 *   返回: { qty, price, priceTypeCode, label, error }
 *   error 非空 = 不应下单
 */
export function buildQuickOrder(row, side, pct, priceType, quoteStore) {
  const code = row?.stock_code
  if (!code) return { qty: 0, error: '无效行, 缺少 stock_code' }

  // 行情检查
  const last = quoteStore?.getLastPrice?.(code) ?? 0
  if (!last) {
    return { qty: 0, error: `无行情 (${code})` }
  }

  // 数量 (配平由调用方传 pct=100 + 自行传 todayBuy/Sell, 或独立 calcBalanceQty)
  const qty = side === 'buy' ? calcBuyQty(row, pct) : calcSellQty(row, pct)
  const err = validateQuick(row, qty, side)
  if (err) return { qty: 0, price: 0, priceTypeCode: 0, label: '', error: err }

  // 价格
  const p = resolvePrice(priceType, code, quoteStore)
  return { qty, price: p.price, priceTypeCode: p.priceTypeCode, label: p.label, error: null }
}
