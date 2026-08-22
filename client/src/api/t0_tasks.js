/**
 * t0_tasks.js — T0Task REST API 客户端（change t0-task-management）
 *
 * 📖 详见 `openspec/specs/trading/spec.md` §REQ-TRADE-013~018
 *
 * 端点（7 个）：
 *   POST   /t0-tasks                    创建
 *   GET    /t0-tasks                    列表
 *   GET    /t0-tasks/overview           整体/单券双视图
 *   GET    /t0-tasks/{id}               详情（含 summary）
 *   PATCH  /t0-tasks/{id}               更新 note/coefficient/target_volume/status
 *   DELETE /t0-tasks/{id}               归档（soft-delete）
 *   POST   /t0-tasks/{id}/close         一键平仓到 base_volume
 *   GET    /t0-tasks/{id}/stats         详细统计（含 daily / by_stock）
 *
 *   注: 无 POST /t0-tasks/{id}/balance 端点（前端在 T0Trade.vue 直接读 holdings.orders 算差值 + 调 /orders/place 下市价单）
 */
import { http } from './http'

export const t0TasksApi = {
  /**
   * 创建 task
   * @param {Object} params
   * @param {string} params.stock_code      带 .SH/.SZ 后缀
   * @param {number} [params.base_volume=0]
   * @param {number} [params.target_volume=0]
   * @param {number} [params.coefficient=1]
   * @param {string} [params.note]
   * @returns {Promise<Object>} 完整 task（含 summary）
   */
  async create({
    stock_code,
    base_volume = 0,
    target_volume = 0,
    coefficient = 1,
    note = null,
  }) {
    const { data } = await http.post('/t0-tasks', {
      stock_code,
      base_volume,
      target_volume,
      coefficient,
      note,
    })
    return data
  },

  /**
   * 列表（可选 status/stock_code 过滤）
   * @param {{status?: string, stock_code?: string}} [opts]
   */
  async list(opts = {}) {
    const params = {}
    if (opts.status) params.status = opts.status
    if (opts.stock_code) params.stock_code = opts.stock_code
    const { data } = await http.get('/t0-tasks', { params })
    return Array.isArray(data) ? data : data?.items || []
  },

  /**
   * 整体 / 单券双视图
   * @returns {Promise<{overall: Object, by_stock: Array}>}
   */
  async overview() {
    const { data } = await http.get('/t0-tasks/overview')
    return data || { overall: {}, by_stock: [] }
  },

  /**
   * task 详情（含 summary: task_net_volume / position_vol / pnl 等）
   * @param {number} taskId
   */
  async get(taskId) {
    const { data } = await http.get(`/t0-tasks/${taskId}`)
    return data
  },

  /**
   * 更新 task（note / coefficient / target_volume / status 任一）
   * @param {number} taskId
   * @param {Object} patch
   */
  async update(taskId, patch) {
    const { data } = await http.patch(`/t0-tasks/${taskId}`, patch)
    return data
  },

  /**
   * 归档 task（soft-delete，等价 status='archived'）
   * @param {number} taskId
   */
  async remove(taskId) {
    const { data } = await http.delete(`/t0-tasks/${taskId}`)
    return data
  },

  /**
   * 一键平仓到 base_volume（返回 action + 委托动作描述）
   * @param {number} taskId
   */
  async close(taskId) {
    const { data } = await http.post(`/t0-tasks/${taskId}/close`)
    return data
  },

  /**
   * 详细统计（summary + daily + by_stock）
   * @param {number} taskId
   */
  async stats(taskId) {
    const { data } = await http.get(`/t0-tasks/${taskId}/stats`)
    return data
  },
}
