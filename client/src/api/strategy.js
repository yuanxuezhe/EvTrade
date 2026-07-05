import { http } from './index'

/**
 * strategy API 客户端（change strategy_trade task 10）
 *
 * 端点：
 * - GET    /api/strategy                          list
 * - POST   /api/strategy                          create（含嵌套 regimes + grids）
 * - GET    /api/strategy/{id}                     detail
 * - PUT    /api/strategy/{id}                     update（status/type/base_volume/note 等）
 * - DELETE /api/strategy/{id}                     cascade delete
 * - POST   /api/strategy/{id}/control             action: pause/resume/stop/clear_now
 * - GET    /api/strategy/{id}/audit?trd_date=yyyymmdd  audit 查询
 * - GET    /api/strategy/flags/definitions        flag 注册表
 */
export const strategyApi = {
  /**
   * 列出策略（按用户隔离；admin 看全部）
   * @param {Object} [opts]
   * @param {string} [opts.status] - active / paused / stopped
   * @param {string} [opts.type]   - general / t0
   * @returns {Promise<Array<Strategy>>}
   */
  async list({ status, type } = {}) {
    const params = {}
    if (status) params.status = status
    if (type) params.type = type
    const { data } = await http.get('/strategy', { params })
    return data
  },

  /**
   * 创建策略（含嵌套 regimes + grids，单事务）
   * @param {Object} payload
   * @returns {Promise<Strategy>}
   */
  async create(payload) {
    const { data } = await http.post('/strategy', payload)
    return data
  },

  /**
   * 详情（含嵌套 regimes.grids）
   * @param {number} id
   * @returns {Promise<Strategy>}
   */
  async getById(id) {
    const { data } = await http.get(`/strategy/${id}`)
    return data
  },

  /**
   * 更新字段（PUT 空字段不会覆盖）
   * @param {number} id
   * @param {Object} patch
   * @returns {Promise<Strategy>}
   */
  async update(id, patch) {
    const { data } = await http.put(`/strategy/${id}`, patch)
    return data
  },

  /**
   * 级联删除
   * @param {number} id
   * @returns {Promise<void>}
   */
  async delete(id) {
    await http.delete(`/strategy/${id}`)
  },

  /**
   * 控制（pause / resume / stop / clear_now）
   * @param {number} id
   * @param {'pause'|'resume'|'stop'|'clear_now'} action
   * @returns {Promise<{ok, action, strategy_id, status}>}
   */
  async control(id, action) {
    const { data } = await http.post(`/strategy/${id}/control`, { action })
    return data
  },

  /**
   * audit 查询
   * @param {number} id
   * @param {string} trdDate - 8 位数字 YYYYMMDD
   * @returns {Promise<Array<AuditRecord>>}
   */
  async getAudit(id, trdDate) {
    const { data } = await http.get(`/strategy/${id}/audit`, {
      params: { trd_date: trdDate },
    })
    return data
  },

  /**
   * flag 注册表（前端下拉数据源；无需灰度门）
   * @returns {Promise<{list: Array<{code, name, category, description}>}>}
   */
  async getFlagDefinitions() {
    const { data } = await http.get('/strategy/flags/definitions')
    return data
  },
}
