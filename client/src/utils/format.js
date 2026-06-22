/**
 * 通用格式化工具
 */
import dayjs from 'dayjs'

export function formatMoney(val, decimals = 2) {
  const n = Number(val)
  if (!Number.isFinite(n)) return '0.00'
  return n.toLocaleString('zh-CN', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals
  })
}

// alias: T0Trade 等模块用 formatAmount
export const formatAmount = formatMoney

export function formatNumber(val) {
  const n = Number(val)
  if (!Number.isFinite(n)) return '0'
  return n.toLocaleString('zh-CN')
}

export function formatPrice(val, decimals = 2) {
  return formatMoney(val, decimals)
}

export function formatPercent(val, decimals = 2) {
  const n = Number(val)
  if (!Number.isFinite(n)) return '0.00%'
  return `${n >= 0 ? '+' : ''}${n.toFixed(decimals)}%`
}

export function formatTime(val, fmt = 'HH:mm:ss') {
  if (!val) return '--'
  const t = dayjs(val)
  if (t.isValid()) return t.format(fmt)
  return String(val)
}

export function formatDateTime(val) {
  if (!val) return '--'
  const t = dayjs(val)
  if (t.isValid()) return t.format('YYYY-MM-DD HH:mm:ss')
  return String(val)
}

/**
 * 委托/成交方向 —— 柜台 order_type 数字串
 *  23 STOCK_BUY   买入
 *  24 STOCK_SELL  卖出
 */
export const ORDER_TYPE_LABEL = {
  '23': '买入',
  '24': '卖出'
}

/** 判断是否买入（股票场景） */
export function isBuyOrderType(orderType) {
  return String(orderType) === '23'
}

/** 取得方向中文标签：买入 / 卖出 / 空串 */
export function orderTypeLabel(orderType) {
  return ORDER_TYPE_LABEL[String(orderType)] || ''
}

/**
 * 委托价格类型 —— 柜台 price_type 数字
 *   5  最新价
 *  11  指定价（限价）
 *  14  对手价
 *  44  市价（最优五档即时成交剩余撤销申报）
 *  ...
 */
export const PRICE_TYPE_LABEL = {
  5: '最新价',
  11: '限价',
  14: '对手价',
  44: '市价'
}

export function priceTypeLabel(p) {
  return PRICE_TYPE_LABEL[Number(p)] || ''
}

/**
 * 委托状态 —— 后端本地推断码（v6 order-pk-by-orderno 起，Order.status 字段语义）
 *  48 unreported           未报
 *  49 pending_report       待报
 *  50 reported             已报
 *  51 reported_cancel      已报待撤
 *  52 partial_pending_cancel 部成待撤
 *  53 partial_cancelled    部撤
 *  54 cancelled            已撤
 *  55 partial              部成
 *  56 filled               已成
 *  57 rejected             废单
 * 255 unknown              未知
 *
 * 与后端 `server/services/push_handlers.py:_infer_order_status` 推断规则一致。
 * 视图层（Trade.vue / Orders.vue）按这些本地推断码分组，不要再用 broker 原始码。
 * 表中保留英文 key 作为兼容入口（旧的 in-memory 状态或前端 fallback）。
 */
export const STATUS_LABEL = {
  // 本地推断码（v6，与后端 push_handlers.py:_status_msg 对齐）
  '48':  '待报',
  '49':  '已报',
  '50':  '部成',
  '51':  '已成',
  '52':  '部撤',
  '53':  '已撤',
  '54':  '已撤单',
  '55':  '废单',
  '56':  '部成部撤',
  '255': '未知',
  // 兼容旧 key（fallback）
  unreported: '待报',
  pending_report: '已报',
  reported: '已报',
  reported_cancel: '已成',
  partial_pending_cancel: '部成',
  partial_cancelled: '部撤',
  cancelled: '已撤',
  partial: '部成',
  filled: '已成',
  rejected: '废单',
  unknown: '未知',
  pending: '已报'
}

export const STATUS_TYPE = {
  // 本地推断码
  '48':  'info',
  '49':  'primary',
  '50':  'warning',
  '51':  'success',
  '52':  'info',
  '53':  'info',
  '54':  'info',
  '55':  'danger',
  '56':  'success',
  '255': 'info',
  // 兼容旧 key
  unreported: 'info',
  pending_report: 'primary',
  reported: 'primary',
  reported_cancel: 'success',
  partial_pending_cancel: 'warning',
  partial_cancelled: 'info',
  cancelled: 'info',
  partial: 'warning',
  filled: 'success',
  rejected: 'danger',
  unknown: 'info',
  pending: 'primary'
}

/** 状态色调分组：pending=等待中, working=进行中, done=终态成功, terminal=终态撤销/废单 */
export const STATUS_TONE = {
  // 本地推断码（v6）
  '48':  'pending',
  '49':  'working',
  '50':  'working',
  '51':  'done',
  '52':  'terminal',
  '53':  'terminal',
  '54':  'terminal',
  '55':  'terminal',
  '56':  'terminal',
  '255': 'pending',
  // 兼容旧 key
  unreported: 'pending',
  pending_report: 'working',
  reported: 'working',
  reported_cancel: 'done',
  partial_pending_cancel: 'working',
  partial_cancelled: 'terminal',
  cancelled: 'terminal',
  partial: 'working',
  filled: 'done',
  rejected: 'terminal',
  unknown: 'pending',
  pending: 'working'
}

/** 状态对应的 Element Plus 图标组件名（运行时由 OrderStatusBadge 解析） */
export const STATUS_ICON_NAME = {
  // 本地推断码
  '48':  'Clock',
  '49':  'Promotion',
  '50':  'Loading',
  '51':  'CircleCheckFilled',
  '52':  'WarningFilled',
  '53':  'RemoveFilled',
  '54':  'CircleClose',
  '55':  'WarningFilled',
  '56':  'WarningFilled',
  '255': 'QuestionFilled',
  // 兼容旧 key
  unreported: 'Clock',
  pending_report: 'Promotion',
  reported: 'Promotion',
  reported_cancel: 'CircleCheckFilled',
  partial_pending_cancel: 'Loading',
  partial_cancelled: 'WarningFilled',
  cancelled: 'CircleClose',
  partial: 'Loading',
  filled: 'CircleCheckFilled',
  rejected: 'WarningFilled',
  unknown: 'QuestionFilled',
  pending: 'Promotion'
}

/** 是否需要脉冲动画（48/49/50 等仍可能在变化的中间态） */
export const STATUS_PULSE = {
  // 本地推断码
  '48':  true,
  '49':  true,
  '50':  true,
  '51':  false,
  '52':  false,
  '53':  false,
  '54':  false,
  '55':  false,
  '56':  false,
  '255': false,
  // 兼容旧 key
  unreported: true,
  pending_report: true,
  reported: true,
  reported_cancel: false,
  partial_pending_cancel: true,
  partial_cancelled: false,
  cancelled: false,
  partial: true,
  filled: false,
  rejected: false,
  unknown: false,
  pending: true
}

/** 状态分类有序列表（用于过滤下拉）—— 用本地推断码作为 value */
export const STATUS_OPTIONS = [
  { value: '48',  label: '待报' },
  { value: '49',  label: '已报' },
  { value: '50',  label: '部成' },
  { value: '51',  label: '已成' },
  { value: '52',  label: '部撤' },
  { value: '53',  label: '已撤' },
  { value: '54',  label: '已撤单' },
  { value: '55',  label: '废单' },
  { value: '56',  label: '部成部撤' },
  { value: '255', label: '未知' }
]

/**
 * 委托 status 终态集合（v6，本地推断码）—— 一旦写入不再被 trd_cfm 覆盖
 * 与后端 `server/services/push_handlers.py:TERMINAL_STATUSES` 一致
 */
export const TERMINAL_STATUSES = new Set(['51', '52', '53', '54', '55', '56'])

/**
 * 委托 status 本地推断（前端镜像后端 _infer_order_status）
 * 与 `server/services/push_handlers.py:_infer_order_status` 逐行一致
 *
 * 规则 (v8: cancelled_volume 主轴):
 *   1. 当前 status 已是终态 (51/52/53/54/55/56) → 保持
 *   2. 撤单主轴 (cum_cancelled):
 *      - cum_cancelled >= vol                 → 53 (已撤)
 *      - cum_cancelled > 0 && cum_traded > 0  → 56 (部成部撤)
 *      - cum_cancelled > 0                    → 53 (部分撤单无成交,视作已撤)
 *   3. broker_status 给出且在 (52, 53, 54) → 撤单类（兼容老 broker）
 *      - cumulative = 0          → 53 (已撤)
 *      - 0 < cumulative < volume → 56 (部成部撤)
 *      - cumulative = volume     → 51 (已成)
 *   4. 累计推断
 *      - cumulative = 0          → 49 (已报)
 *      - 0 < cumulative < volume → 50 (部成)
 *      - cumulative = volume     → 51 (已成)
 *
 * @param {Object} order - { status, traded_volume, cancelled_volume, volume }
 * @param {string|null} brokerStatus - 可选,broker ord_cfm 推的 status 字段
 * @returns {string} 推断后的 status
 */
export function inferOrderStatus(order, brokerStatus = null) {
  const current = String(order?.status || '48')

  // 1. 终态保持
  if (TERMINAL_STATUSES.has(current)) return current

  const cum = Number(order?.traded_volume) || 0
  const cumCancelled = Number(order?.cancelled_volume) || 0
  const vol = Number(order?.volume) || 0

  // 2. 撤单主轴（v8 新增,优先于 broker_status 判定）
  if (cumCancelled >= vol && vol > 0) return '53'  // 已撤
  if (cumCancelled > 0 && cum > 0) return '56'  // 部成部撤
  if (cumCancelled > 0 && cum === 0) return '53'  // 部分撤单无成交 → 已撤

  // 3. broker 推了撤单类 status
  if (brokerStatus && ['52', '53', '54'].includes(String(brokerStatus))) {
    if (cum === 0) return '53'
    if (cum < vol) return '56'
    return '51'
  }

  // 4. 累计推断
  if (cum === 0) return '49'
  if (cum < vol) return '50'
  return '51'
}
