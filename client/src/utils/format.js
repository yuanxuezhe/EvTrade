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
 * 委托状态 —— 柜台原始数字（broker wire format）
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
 * 后端已统一返回柜台数字；前端按数字翻译成汉字。
 * 表中保留英文 key 作为兼容入口（旧的 in-memory 状态或前端 fallback）。
 */
export const STATUS_LABEL = {
  // 柜台数字
  '48':  '未报',
  '49':  '待报',
  '50':  '已报',
  '51':  '已报待撤',
  '52':  '部成待撤',
  '53':  '部撤',
  '54':  '已撤',
  '55':  '部成',
  '56':  '已成',
  '57':  '废单',
  '255': '未知',
  // 兼容旧 key
  unreported: '未报',
  pending_report: '待报',
  reported: '已报',
  reported_cancel: '已报待撤',
  partial_pending_cancel: '部成待撤',
  partial_cancelled: '部撤',
  cancelled: '已撤',
  partial: '部成',
  filled: '已成',
  rejected: '废单',
  unknown: '未知',
  pending: '已报'
}

export const STATUS_TYPE = {
  // 柜台数字
  '48':  'info',
  '49':  'info',
  '50':  'primary',
  '51':  'warning',
  '52':  'warning',
  '53':  'info',
  '54':  'info',
  '55':  'warning',
  '56':  'success',
  '57':  'danger',
  '255': 'info',
  // 兼容旧 key
  unreported: 'info',
  pending_report: 'info',
  reported: 'primary',
  reported_cancel: 'warning',
  partial_pending_cancel: 'warning',
  partial_cancelled: 'info',
  cancelled: 'info',
  partial: 'warning',
  filled: 'success',
  rejected: 'danger',
  unknown: 'info',
  pending: 'primary'
}

/** 状态色调分组：pending=等待中，working=进行中，done=终态成功，terminal=终态撤销/废单 */
export const STATUS_TONE = {
  // 柜台数字
  '48':  'pending',
  '49':  'pending',
  '50':  'pending',
  '51':  'terminal',
  '52':  'working',
  '53':  'terminal',
  '54':  'terminal',
  '55':  'working',
  '56':  'done',
  '57':  'terminal',
  '255': 'pending',
  // 兼容旧 key
  unreported: 'pending',
  pending_report: 'pending',
  reported: 'pending',
  reported_cancel: 'terminal',
  partial_pending_cancel: 'working',
  partial_cancelled: 'terminal',
  cancelled: 'terminal',
  partial: 'working',
  filled: 'done',
  rejected: 'terminal',
  unknown: 'pending',
  pending: 'pending'
}

/** 状态对应的 Element Plus 图标组件名（运行时由 OrderStatusBadge 解析） */
export const STATUS_ICON_NAME = {
  // 柜台数字
  '48':  'Document',
  '49':  'Clock',
  '50':  'Promotion',
  '51':  'CircleClose',
  '52':  'WarningFilled',
  '53':  'RemoveFilled',
  '54':  'CircleClose',
  '55':  'Loading',
  '56':  'CircleCheckFilled',
  '57':  'WarningFilled',
  '255': 'QuestionFilled',
  // 兼容旧 key
  unreported: 'Document',
  pending_report: 'Clock',
  reported: 'Promotion',
  reported_cancel: 'CircleClose',
  partial_pending_cancel: 'WarningFilled',
  partial_cancelled: 'RemoveFilled',
  cancelled: 'CircleClose',
  partial: 'Loading',
  filled: 'CircleCheckFilled',
  rejected: 'WarningFilled',
  unknown: 'QuestionFilled',
  pending: 'Promotion'
}

/** 是否需要脉冲动画（待报/已报 等仍可能在变化的中间态） */
export const STATUS_PULSE = {
  // 柜台数字
  '48':  true,
  '49':  true,
  '50':  true,
  '51':  false,
  '52':  true,
  '53':  false,
  '54':  false,
  '55':  true,
  '56':  false,
  '57':  false,
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

/** 状态分类有序列表（用于过滤下拉）—— 用柜台数字作为 value */
export const STATUS_OPTIONS = [
  { value: '48',  label: '未报' },
  { value: '49',  label: '待报' },
  { value: '50',  label: '已报' },
  { value: '51',  label: '已报待撤' },
  { value: '52',  label: '部成待撤' },
  { value: '53',  label: '部撤' },
  { value: '54',  label: '已撤' },
  { value: '55',  label: '部成' },
  { value: '56',  label: '已成' },
  { value: '57',  label: '废单' },
  { value: '255', label: '未知' }
]
