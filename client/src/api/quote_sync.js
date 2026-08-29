/**
 * quoteSync API 客户端 (his-quote-backfill change)
 *
 * 端点 (前缀 /api/quote-sync, http baseURL 已含 /api, 路径不带 /api):
 * - GET    /quote-sync              列行情同步任务表 (配置)
 * - POST   /quote-sync              新增配置行
 * - DELETE /quote-sync/{stock}      删配置 (不删 minute_bars 数据)
 * - PATCH  /quote-sync/{stock}      改 auto_sync / end_date
 * - POST   /quote-sync/sync         按日同步 {stock_code, date} → 成功 {code:0,...} / 失败 {code:1,msg}
 *
 * 鉴权: 全部 require_admin
 * 注意: /sync 失败体 {code:1, msg} 不含 list/data, 不走 http 拦截器全局 toast,
 *       由页面读 code 行内显示失败原因 (符合"失败显示原因")。
 */
import { http } from './http'

export const quoteSyncApi = {
  /** 列配置 (任务表) — 返 [{stock_code,start_date,end_date,last_loaded_date,auto_sync}, ...] */
  list: () => http.get('/quote-sync').then((r) => r.data),

  /** 新增配置行 — 返 data 对象 */
  add: (data) => http.post('/quote-sync', data).then((r) => r.data),

  /** 删配置 (不删数据) */
  remove: (stockCode) => http.delete(`/quote-sync/${stockCode}`).then((r) => r.data),

  /** 改 auto_sync / end_date */
  patch: (stockCode, data) => http.patch(`/quote-sync/${stockCode}`, data).then((r) => r.data),

  /** 按日同步 {stock_code, date} — 返 {code, msg, bars?, last_loaded_date?}
   *  code:0 成功 (含假日 0 根) / code:1 失败 (msg=原因) */
  syncDay: (stockCode, date) =>
    http.post('/quote-sync/sync', { stock_code: stockCode, date }).then((r) => r.data),
}
