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
 * 委托/成交方向
 */
export const DIRECTION_LABEL = {
  BUY: '买入',
  SELL: '卖出'
}

/**
 * 委托状态 —— 对应 XtConstant 11 个状态码
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
 */
export const STATUS_LABEL = {
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
  // 兼容旧 key
  pending: '已报'
}

export const STATUS_TYPE = {
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

/** 状态分类有序列表（用于过滤下拉） */
export const STATUS_OPTIONS = [
  { value: 'unreported', label: '未报' },
  { value: 'pending_report', label: '待报' },
  { value: 'reported', label: '已报' },
  { value: 'reported_cancel', label: '已报待撤' },
  { value: 'partial_pending_cancel', label: '部成待撤' },
  { value: 'partial_cancelled', label: '部撤' },
  { value: 'cancelled', label: '已撤' },
  { value: 'partial', label: '部成' },
  { value: 'filled', label: '已成' },
  { value: 'rejected', label: '废单' },
  { value: 'unknown', label: '未知' }
]
