/**
 * holdings_helpers.js — holdings store 纯函数 helper
 *
 * phase-2 抽取：保持 holdings.js 单 store facade (R3),
 * 把无 Pinia state 依赖的纯函数放到独立模块
 *
 * 包含：
 *   parseAsset — 解包 api.getAsset() 响应（拦截器可能解到 list 或 单对象）
 *   recomputeStatus — 委托 status 防御性重算 helper
 *   _now_hms — HH:MM:SS 字符串
 *   _today_yyyymmdd — 今日 YYYYMMDD 字符串
 *
 * change system-delegation-price-fill-calc re-export:
 *   normalizeTrade / recomputeOrderFromTrade / metaMerge / flattenCancelledByRow
 *   （实际定义在 utils/orderCalc.js, 此处 re-export 保持现有调用方不动）
 */
import { inferOrderStatus } from '../utils/format'
import {
  normalizeTrade,
  normalizeOrder,
  recomputeOrderFromTrade,
  metaMerge,
  flattenCancelledByRow
} from '../utils/orderCalc'

/**
 * 解包 api.getAsset() 响应 → 标准化 asset 对象
 * 后端返 {code:0, msg:"", list:[{cash, ...}]}，拦截器解包后可能是 list 或单对象
 */
export function parseAsset(resp) {
  const list = Array.isArray(resp) ? resp : (Array.isArray(resp?.list) ? resp.list : [resp])
  const a = list[0]
  if (!a) return null
  return {
    cash: Number(a.cash) || 0,
    available: Number(a.available) || Number(a.cash) || 0,  // available 透传 (兼容旧 api 响应无该字段)
    frozen_cash: Number(a.frozen_cash) || 0,
    market_value: Number(a.market_value) || 0,
    total_asset: Number(a.total_asset) || 0,
    last_asset: Number(a.last_asset) || 0   // 期初总资产 (早上 init 锁定)
  }
}

/**
 * 委托 status 防御性重算 helper
 *   - 入参 row (任意对象,只要含 volume/traded_volume/cancelled_volume 可选)
 *   - 返回新对象(不可变),status = inferOrderStatus({...row}, null)
 *   - 不传 brokerStatus: 完全按 traded_volume / cancelled_volume / volume 推断
 *     满足用户需求"按已成/撤单数量计算状态"
 *   - 缺 volume 或 traded_volume 时原样返回
 *   - 用于: bootstrap / refresh / applyOrderPush 三处入口
 */
export function recomputeStatus(o) {
  if (o == null) return o
  if (o.volume == null || o.traded_volume == null) return o
  return {
    ...o,
    status: inferOrderStatus(
      {
        status: o.status,
        volume: o.volume,
        traded_volume: o.traded_volume,
        cancelled_volume: o.cancelled_volume
      },
      null
    )
  }
}

/** HH:MM:SS 当前时间 */
export function nowHMS() {
  const d = new Date()
  return [d.getHours(), d.getMinutes(), d.getSeconds()]
    .map((n) => String(n).padStart(2, '0')).join(':')
}

// 跟后端 trd_date 格式对齐 (YYYYMMDD)
export function todayYYYYMMDD() {
  const d = new Date()
  return [d.getFullYear(), d.getMonth() + 1, d.getDate()]
    .map((n) => String(n).padStart(2, '0')).join('')
}

// change system-delegation-price-fill-calc: re-export 5 个独立计算工具
// （定义在 utils/orderCalc.js, 此处 re-export 保持现有调用方不动）
export {
  normalizeTrade,
  normalizeOrder,
  recomputeOrderFromTrade,
  metaMerge,
  flattenCancelledByRow
}
