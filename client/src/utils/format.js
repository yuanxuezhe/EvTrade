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

// 价格格式化统一走 `composables/usePricePrecision.js` 的 formatPrice(price, stockCode),
//   按 stockScale(code) 精度补 0. 这里只保留金额/最新价工具 (formatMoney / formatPriceAuto).

// 价格智能格式化 — 保留最多 4 位有效小数, 去尾 0 (0.0039 → "0.0039", 12.5 → "12.5", 12.00 → "12")
// 用于最新价/卖一价/买一价 sub 标签, 避免 0.0039 被 formatMoney 截成 "0.00"
export function formatPriceAuto(val) {
  const n = Number(val)
  if (!Number.isFinite(n) || n === 0) return '0'
  // toFixed(4) 保留 4 位小数, 再用正则去掉尾部 0 和孤立的 .
  return n.toFixed(4).replace(/(\.\d*?)0+$/, '$1').replace(/\.$/, '')
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
 * 委托 status —— broker xtconstant 字典（change align-status-codes-to-xtconstant）
 *  48 ORDER_UNREPORTED        未报
 *  49 ORDER_WAIT_REPORTING    待报
 *  50 ORDER_REPORTED          已报
 *  51 ORDER_REPORTED_CANCEL   已报待撤
 *  52 ORDER_PARTSUCC_CANCEL   部成待撤
 *  53 ORDER_PART_CANCEL       部成部撤
 *  54 ORDER_CANCELED          已撤
 *  55 ORDER_PART_SUCC         部成
 *  56 ORDER_SUCCEEDED         已成
 *  57 ORDER_JUNK              废单
 * 255 ORDER_UNKNOWN           未知
 *
 * 与后端 `server/services/order_status.py:_infer_order_status` 推断规则一致（全部 broker 码）。
 * 视图层（Trade.vue / Orders.vue）按 broker xtconstant 字典分组，不用本地推断码。
 * 不提供旧 14 个英文 fall-back 兼容 key（grep 0 处外部引用）。
 */
export const STATUS_LABEL = {
  '48':  '待报',   // 与后端一致 (broker 反馈前)
  '49':  '待报',
  '50':  '已报',
  '51':  '已报待撤',
  '52':  '部成待撤',
  '53':  '部成部撤',
  '54':  '已撤',
  '55':  '部成',
  '56':  '已成',
  '57':  '废单',
  '255': '未知'
}

/** Element Plus tag type (颜色) */
export const STATUS_TYPE = {
  '48':  'info',// 待报
  '49':  'info',      // 待报
  '50':  'primary',   // 已报
  '51':  'warning',   // 已报待撤
  '52':  'warning',   // 部成待撤
  '53':  'info',      // 部成部撤
  '54':  'info',      // 已撤
  '55':  'warning',   // 部成
  '56':  'success',   // 已成
  '57':  'danger',    // 废单
  '255': 'info'       // 未知
}

/**
 * 委托状态阶段 rank (订单生命周期单调递增)
 * 用于前端 ws 推送守门: new_rank >= current_rank 才更新+弹窗, 防止状态倒退
 *
 * 阶段划分 (broker xtconstant 码):
 *   rank 1: 48/49  待报/未报 (初始)
 *   rank 2: 50     已报
 *   rank 3: 51     已报待撤 (撤单流程开始)
 *          55     部成 (成交流程进行中)
 *   rank 4: 52     部成待撤
 *   rank 5: 53/54/56/57/255  终态 (部成部撤/已撤/已成/废单/未知)
 *
 * rank 3 并行: 51(撤单中) 与 55(部成) 互不倒退, 业务上 55->52(部成后撤单) rank 3->4 向后推进放行
 */
export const STATUS_RANK = {
  '48': 1,  '49': 1,
  '50': 2,
  '51': 3,  '55': 3,
  '52': 4,
  '53': 5,  '54': 5,  '56': 5,  '57': 5,  '255': 5,
}

/** 取状态阶段 rank; 未知状态返 0 (放行, 不阻塞首次写入) */
export function statusRank(s) {
  return STATUS_RANK[String(s)] ?? 0
}

/** 状态色调分组：pending=等待中, working=进行中, done=终态成功, terminal=终态撤销/废单 */
export const STATUS_TONE = {
  '48':  'pending',// 待报
  '49':  'pending',  // 待报
  '50':  'working',  // 已报
  '51':  'working',  // 已报待撤 (撤单过渡)
  '52':  'working',  // 部成待撤 (撤单过渡)
  '53':  'done',     // 部成部撤 (算完成态)
  '54':  'terminal', // 已撤
  '55':  'done',     // 部成
  '56':  'done',     // 已成
  '57':  'terminal', // 废单
  '255': 'pending'   // 未知
}

/** 状态对应的 Element Plus 图标组件名 */
export const STATUS_ICON_NAME = {
  '48':  'Clock',// 待报
  '49':  'Clock',             // 待报
  '50':  'Promotion',          // 已报
  '51':  'Loading',           // 已报待撤
  '52':  'Loading',           // 部成待撤
  '53':  'WarningFilled',     // 部成部撤
  '54':  'CircleClose',       // 已撤
  '55':  'Loading',           // 部成
  '56':  'CircleCheckFilled', // 已成
  '57':  'WarningFilled',     // 废单
  '255': 'QuestionFilled'     // 未知
}

/** 是否需要脉冲动画（48/49/50/51/52/55 等仍可能在变化的中间态） */
export const STATUS_PULSE = {
  '48':  true,// 待报
  '49':  true,    // 待报
  '50':  true,    // 已报
  '51':  true,    // 已报待撤
  '52':  true,    // 部成待撤
  '53':  false,   // 部成部撤 (终态)
  '54':  false,   // 已撤 (终态)
  '55':  true,    // 部成 (中间态)
  '56':  false,   // 已成 (终态)
  '57':  false,   // 废单 (终态)
  '255': false    // 未知 (终态)
}

/** 状态分类有序列表（用于过滤下拉）—— 用 broker xtconstant 字典作为 value */
export const STATUS_OPTIONS = [
  { value: '48',  label: '未报' },
  { value: '49',  label: '待报' },
  { value: '50',  label: '已报' },
  { value: '51',  label: '已报待撤' },
  { value: '52',  label: '部成待撤' },
  { value: '53',  label: '部成部撤' },
  { value: '54',  label: '已撤' },
  { value: '55',  label: '部成' },
  { value: '56',  label: '已成' },
  { value: '57',  label: '废单' },
  { value: '255', label: '未知' }
]

/**
 * 委托 status 终态集合（broker xtconstant 字典）
 * 与后端 `server/services/order_status.py:TERMINAL_STATUSES` 一致
 *
 * 包含: broker 52 (部成待撤, 撤单过渡) + broker 53/54/56/57 (部成部撤/已撤/已成/废单)
 * 不含: broker 55 (部成 / PART_SUCC, 非终态, 仍可继续累计到 broker 56 已成)
 */
export const TERMINAL_STATUSES = new Set(['52', '53', '54', '56', '57'])

/**
 * 委托 status 本地推断（前端镜像后端 _infer_order_status, broker 码输出）
 * 与 `server/services/order_status.py:_infer_order_status` 逐行一致
 *
 * 规则 (cancelled_volume 主轴 + broker 码输出):
 *   1. 当前 status 已是终态 (52/53/54/55/56/57) → 保持
 *   2. 撤单主轴 (cum_cancelled):
 *      - cum_cancelled >= vol                 → 54 (broker 已撤)
 *      - cum_cancelled > 0 && cum_traded > 0  → 53 (broker 部成部撤)
 *      - cum_cancelled > 0                    → 54 (部分撤单无成交, 视作 broker 已撤)
 *   3. broker_status 给出且在 (51, 52, 53, 54) → 撤单类（兼容老 broker）
 *      - cumulative = 0          → 54 (broker 已撤)
 *      - 0 < cumulative < volume → 53 (broker 部成部撤)
 *      - cumulative = volume     → 56 (broker 已成)
 *   4. 累计推断 (broker 码)
 *      - cumulative = 0          → 50 (broker 已报)
 *      - 0 < cumulative < volume → 55 (broker 部成)
 *      - cumulative = volume     → 56 (broker 已成)
 *
 * @param {Object} order - { status, traded_volume, cancelled_volume, volume }
 * @param {string|null} brokerStatus - 可选, broker ord_cfm 推的 status 字段
 * @returns {string} 推断后的 status (broker xtconstant 码)
 */
export function inferOrderStatus(order, brokerStatus = null) {
  const current = String(order?.status || '48')

  // 1. 终态保持
  if (TERMINAL_STATUSES.has(current)) return current

  const cum = Number(order?.traded_volume) || 0
  const cumCancelled = Number(order?.cancelled_volume) || 0
  const vol = Number(order?.volume) || 0

  // 2. 撤单主轴（优先于 broker_status 判定）
  if (cumCancelled >= vol && vol > 0) return '54'  // broker 已撤
  if (cumCancelled > 0 && cum > 0) return '53'      // broker 部成部撤
  if (cumCancelled > 0 && cum === 0) return '54'    // broker 已撤 (部分撤单无成交)

  // 3. broker 推了撤单类 status (含 broker 51 已报待撤)
  // REQ-TRADE-035: 废单 57 直接保留 — broker 拒单不可能有任何成交/撤单,
  //   fall-through 到第 4 段会被错判成 '50' 已报
  if (brokerStatus && String(brokerStatus) === '57') return '57'
  if (brokerStatus && ['51', '52', '53', '54'].includes(String(brokerStatus))) {
    if (cum === 0) return '54'      // broker 已撤
    if (cum < vol) return '53'      // broker 部成部撤
    return '56'                      // broker 已成
  }

  // 4. 累计推断 (broker 码)
  if (cum === 0) return '50'        // broker 已报
  if (cum < vol) return '55'        // broker 部成
  return '56'                        // broker 已成
}