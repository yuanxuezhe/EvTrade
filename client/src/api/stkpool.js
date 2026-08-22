/**
 * stkpool API 客户端 (add-stkpool-module change)
 *
 * 端点 (前缀 /api/stkpool, 通过 axios http 的 baseURL 已含 /api):
 * - GET    /api/stkpool                       全量主表
 * - POST   /api/stkpool                       创建池
 * - PUT    /api/stkpool/{pool_id}             改池名/备注
 * - DELETE /api/stkpool/{pool_id}             删池 (CASCADE 清明细)
 * - GET    /api/stkpool/{pool_id}/detail      池明细
 * - POST   /api/stkpool/{pool_id}/detail      加明细
 * - DELETE /api/stkpool/{pool_id}/detail/{stock_code}  删明细
 *
 * 鉴权: 全部走 auth 通用拦截器 (http 401 by deps)
 */
import { http } from './http'

// 注意: http 实例 baseURL = '/api', 调用路径必须不带 /api 前缀
export const stkpoolApi = {
  /** 全量主表 (id ASC) — 返 [{id, name, remark, created_at}, ...] */
  list: () => http.get('/stkpool').then(r => {
    const body = r.data
    // 后端返 {pools: [...]} 形态
    return body?.pools ?? body ?? []
  }),

  /** 创建池 */
  create: (data) => http.post('/stkpool', data).then(r => r.data),

  /** 改池 (partial update) */
  update: (id, data) => http.put(`/stkpool/${id}`, data).then(r => r.data),

  /** 删池 (CASCADE 清明细) */
  remove: (id) => http.delete(`/stkpool/${id}`),

  /** 池明细列表 */
  detail: (id) => http.get(`/stkpool/${id}/detail`).then(r => {
    const body = r.data
    return body?.details ?? body ?? []
  }),

  /** 加明细 (idempotent) — 支持批量, stock_codes 数组转逗号串 */
  detailAdd: (id, stockCodes) => {
    // 兼容旧调用: 单个字符串 / 单只股票
    const arr = Array.isArray(stockCodes) ? stockCodes : [stockCodes]
    return http.post(`/stkpool/${id}/detail`, {
      stock_codes: arr.join(',')
    }).then(r => r.data)
  },

  /** 删明细 */
  detailRemove: (id, stock_code) => http.delete(`/stkpool/${id}/detail/${stock_code}`),
}