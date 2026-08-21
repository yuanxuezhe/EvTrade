/**
 * script_strategy.js — script-strategy change: 前端 API 客户端 (v123)
 *
 * 端点前缀: /api/script-strategy
 *
 * 模块结构 (v123 三层模型: script → strategy → strategy_task):
 *   Script CRUD:   listScripts / getScript / createScript / updateScript / deleteScript / getDefaultTemplate
 *   Strategy CRUD: listStrategies / getStrategy / createStrategy / updateStrategy / deleteStrategy
 *   回测/批次:     backtestStrategy / listBatches / listBatchTasks
 *   Task 控制:     listTasks / getTask / stopTask / deleteTask / getTaskLogs / getTaskSignals
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

  async compileScript(id) {
    // 2026-08-21: 静态语法检查（ast.parse，不跑回测）
    // 返 {ok: true, warnings: []} 或 {ok: false, error: {line, col, msg}}
    const { data } = await http.post(`/script-strategy/scripts/${id}/compile`)
    return data
  },

  async getDefaultTemplate() {
    const { data } = await http.get('/script-strategy/templates/default')
    return data
  },

  // ─────────────── Strategy CRUD (v123) ───────────────

  async listStrategies({ status = null, only_mine = false } = {}) {
    const params = {}
    if (status) params.status = status
    if (only_mine) params.only_mine = only_mine
    const { data } = await http.get('/script-strategy/strategies', { params })
    return data
  },

  async getStrategy(id) {
    const { data } = await http.get(`/script-strategy/strategies/${id}`)
    return data
  },

  async createStrategy(payload) {
    // payload: { name, script_id, stock_code } (标的必填, 策略只针对此标的回测)
    const { data } = await http.post('/script-strategy/strategies', payload)
    return data
  },

  async updateStrategy(id, patch) {
    const { data } = await http.put(`/script-strategy/strategies/${id}`, patch)
    return data
  },

  async deleteStrategy(id) {
    await http.delete(`/script-strategy/strategies/${id}`)
  },

  // ─────────────── 回测 / 批次 (v123) ───────────────

  async backtestStrategy(id, payload) {
    // payload: { mode, stock_code, backtest_start_date, backtest_end_date,
    //           params | param_ranges, period, metric, concurrency }
    const { data } = await http.post(`/script-strategy/strategies/${id}/backtest`, payload)
    return data
  },

  async listBatches(id) {
    const { data } = await http.get(`/script-strategy/strategies/${id}/batches`)
    return data
  },

  async listBatchTasks(id, batchNo) {
    const { data } = await http.get(`/script-strategy/strategies/${id}/batches/${batchNo}/tasks`)
    return data
  },

  // v124: 重测批次 (新 batch, 原批次 task 废弃)
  async retestBatch(id, batchNo) {
    const { data } = await http.post(`/script-strategy/strategies/${id}/batches/${batchNo}/retest`)
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

  async getTaskSignals(id, { type = null, limit = 500 } = {}) {
    const params = { limit }
    if (type) params.type = type
    const { data } = await http.get(`/script-strategy/tasks/${id}/signals`, { params })
    return data
  },

  // ─────────────── 策略下单母单 (v126) ───────────────

  async createStrategyOrder(strategyId) {
    const { data } = await http.post('/script-strategy/strategy-orders', { strategy_id: strategyId })
    return data
  },

  async listStrategyOrders() {
    const { data } = await http.get('/script-strategy/strategy-orders')
    return data
  },

  async getStrategyOrder(id) {
    const { data } = await http.get(`/script-strategy/strategy-orders/${id}`)
    return data
  },

  async listStrategyOrderChildren(id) {
    const { data } = await http.get(`/script-strategy/strategy-orders/${id}/children`)
    return data
  },

  async startStrategyOrder(id) {
    const { data } = await http.post(`/script-strategy/strategy-orders/${id}/start`)
    return data
  },

  async stopStrategyOrder(id) {
    const { data } = await http.post(`/script-strategy/strategy-orders/${id}/stop`)
    return data
  },

  async closeStrategyOrder(id) {
    const { data } = await http.post(`/script-strategy/strategy-orders/${id}/close`)
    return data
  },
}
