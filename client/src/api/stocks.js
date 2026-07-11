import { http } from './index'

/**
 * stocks API 客户端 (v22 stock-info-editor)
 *
 * 端点：
 * - GET    /api/stocks              列表(任意登录用户)
 * - GET    /api/stocks/{code}       详情
 * - PATCH  /api/stocks/{code}       admin 编辑 (admin only)
 */
export const stocksApi = {
  /**
   * 列表
   * @param {Object} params { industry?, market?, limit? }
   * @returns {Promise<Array>} 形如 [{stock_code, stock_name, industry, ...}]
   *   后端返回 {code, msg, list}, 由 http 拦截器自动解包为 list
   */
  async list(params = {}) {
    const { data } = await http.get('/stocks', { params })
    return data
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
      // 404 → null
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
  }
}