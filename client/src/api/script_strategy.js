/**
 * script_strategy.js — script-strategy change: 前端 API 客户端
 *
 * 端点前缀: /api/script-strategy
 *
 * 模块结构:
 *   Script CRUD:  listScripts / getScript / createScript / updateScript / deleteScript
 *   Task 控制:    listTasks / getTask / createTask / stopTask / deleteTask / getTaskLogs
 *   Template:     getDefaultTemplate
 */
import { http } from './index'

export const scriptStrategyApi = {
  // ─────────────── Script CRUD ───────────────

  async listScripts(only_mine) {
    const params = only_mine ? { only_mine } : {}
    const { data } = await http.get('/script-strategy/scripts', { params })
    return data
  },

  async getScript(id) {
    const { data } = await http.get(`/script-strategy/scripts/${id}`)
    return data
  },

  async createScript(payload) {
    const { data } = await http.post('/script-strategy/scripts', payload)
    return data
  },

  async updateScript(id, patch) {
    const { data } = await http.put(`/script-strategy/scripts/${id}`, patch)
    return data
  },

  async deleteScript(id) {
    await http.delete(`/script-strategy/scripts/${id}`)
  },

  async getDefaultTemplate() {
    const { data } = await http.get('/script-strategy/templates/default')
    return data
  },

  // ─────────────── Task 控制 ───────────────

  async listTasks(params = {}) {
    const { data } = await http.get('/script-strategy/tasks', { params })
    return data
  },

  async getTask(id) {
    const { data } = await http.get(`/script-strategy/tasks/${id}`)
    return data
  },

  async createTask(payload) {
    // 不带 mode (创建时不指定, 由 run 决定)
    const { data } = await http.post('/script-strategy/tasks', payload)
    return data
  },

  async runTask(id, payload) {
    // 触发任务执行: payload 含 mode (backtest/live) + 回测专属 start/end/period
    const { data } = await http.post(`/script-strategy/tasks/${id}/run`, payload)
    return data
  },

  async runSweepTask(id, payload) {
    // v122+ 参数扫描: payload 含 param_grid + metric + select_top_n + concurrency
    // 返 { sweep_id, total_runs, summary_task_id }
    const { data } = await http.post(`/script-strategy/tasks/${id}/run-sweep`, payload)
    return data
  },

  async stopTask(id) {
    const { data } = await http.post(`/script-strategy/tasks/${id}/stop`)
    return data
  },

  async deleteTask(id) {
    await http.delete(`/script-strategy/tasks/${id}`)
  },

  async getTaskLogs(id) {
    const { data } = await http.get(`/script-strategy/tasks/${id}/logs`)
    return data
  },

  async listFinishedBacktests({ scriptId, hasBestParams = true, limit = 50 } = {}) {
    // v122+ 拉历史 backtest (含 sweep summary) 供 live 选参数
    // has_best_params=1 限定 best_params 非空 (单 run + sweep summary)
    const params = { has_best_params: hasBestParams ? 1 : 0, limit }
    if (scriptId) params.script_id = scriptId
    return this.listTasks(params)
  },

  async getTaskSignals(id, { type = null, limit = 500 } = {}) {
    const params = { limit }
    if (type) params.type = type
    const { data } = await http.get(`/script-strategy/tasks/${id}/signals`, { params })
    return data
  },
}