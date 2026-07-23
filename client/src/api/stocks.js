import axios from 'axios'
import { http } from './index'

/**
 * stocks API 客户端
 * v25 stocks-cache-and-short-name: 真分页 page/page_size + total + short_name
 *
 * 端点：
 * - GET    /api/stocks              列表(真分页 + 服务端筛选)
 * - GET    /api/stocks/{code}       详情
 * - PATCH  /api/stocks/{code}       admin 编辑 (v22, v23, v25 字段同步)
 *
 * 注意：/api/stocks 真分页响应含 {code, msg, list, total, page, page_size}
 *  http 拦截器默认会把 res.data 解包为 list（丢 total）
 *  所以 list() 用裸 axios 实例（不走拦截器）拿到原始 body
 *  getOne/update 仍走 http（响应无 total）
 */

// 裸 axios 实例（不走解包拦截器，但仍带 401 由 http 拦截器统一处理）
const rawHttp = axios.create({
  baseURL: '/api',
  timeout: 30000
})

// token 注入（同步 http.interceptors.request 逻辑）
rawHttp.interceptors.request.use((config) => {
  const token = localStorage.getItem('evtrade-token')
  if (token) {
    config.headers = config.headers || {}
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 401 处理 — 与 http 拦截器一致
let onUnauthorized = null
export function setUnauthorizedHandler(fn) {
  onUnauthorized = fn
}
rawHttp.interceptors.response.use(
  (res) => res,
  (err) => {
    const status = err.response?.status
    if (status === 401) {
      localStorage.removeItem('evtrade-token')
      if (onUnauthorized) onUnauthorized()
    }
    return Promise.reject(err)
  }
)

export const stocksApi = {
  /**
   * 列表（真分页）
   * @param {Object} params { sector?, keyword?, is_t0_able?, page?, page_size? }
   * @returns {Promise<{list: Array, total: number, page: number, page_size: number}>}
   */
  async list(params = {}) {
    const { data } = await rawHttp.get('/stocks', { params })
    // 响应: {code: 0, msg: "ok", list: [...], total: N, page, page_size}
    if (data && data.code === 0) {
      return {
        list: data.list || [],
        total: data.total || 0,
        page: data.page || 1,
        page_size: data.page_size || 100
      }
    }
    throw new Error(data?.msg || 'stocks list failed')
  },

  /**
   * 全量证券信息 (v90 前端 IndexedDB 首次/同步缓存用, 不分页)
   * 1 次拉完所有 stocks 行 (to_dict 全 9 字段)
   * @returns {Promise<{list: Array, total: number}>}
   */
  async listAll() {
    const { data } = await rawHttp.get('/stocks/all')
    if (data && data.code === 0) {
      return {
        list: data.list || [],
        total: data.total || 0
      }
    }
    throw new Error(data?.msg || 'stocks listAll failed')
  },

  /**
   * 单只详情
   * @returns {Promise<Object|null>} 后端返回 {code, msg, data}, 拦截器解包为 data
   *   注意：404 时 throw（API 拦截器对非 RPC 错误透传）
   */
  async getOne(stockCode) {
    try {
      const { data } = await http.get(`/stocks/${encodeURIComponent(stockCode)}`)
      return data
    } catch (e) {
      if (e?.response?.status === 404) return null
      throw e
    }
  },

  /**
   * admin 编辑
   * @param {string} stockCode
   * @param {Object} payload 只含需要修改的字段(后端按 exclude_none 处理)
   * @returns {Promise<Object>} 更新后的完整 stock
   */
  async update(stockCode, payload) {
    const { data } = await http.patch(
      `/stocks/${encodeURIComponent(stockCode)}`,
      payload
    )
    return data
  },

  /**
   * admin 添加证券 (v46 stock-info-create, REQ-STOCK-006)
   * @param {Object} payload 8 字段: stock_code(必填) + stock_name(必填) + 可选 sector/short_name/is_t0_able/min_buy_qty/trade_unit
   * @returns {Promise<Object>} 新插入的完整 stock
   *   错误处理: 409 (重复) / 422 (字段校验失败) 由调用方 catch
   */
  async create(payload) {
    const { data } = await http.post('/stocks', payload)
    return data
  }
}