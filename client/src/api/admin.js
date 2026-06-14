import { http } from './index'

// ============================================================
// 管理 API（v4 系统初始化 + 对账 + 时段 + 费率）
// 后端路由前缀: /api/admin/*  /api/fee-config
// ============================================================

// 交易日管理
export const tradingDayApi = {
  // 当前激活交易日 + 历史 90 天
  async current() {
    const res = await http.get('/admin/trading-day')
    return res.data
  },
  // 触发日初（对账 + 切日）
  async init(trdDate) {
    const res = await http.post('/admin/trading-day/init', { trd_date: trdDate })
    return res.data
  },
  // 关闭当前日
  async close() {
    const res = await http.post('/admin/trading-day/close')
    return res.data
  }
}

// 对账管理
export const reconcileApi = {
  // 读配置
  async getConfig() {
    const res = await http.get('/admin/reconcile/config')
    return res.data
  },
  // 改配置（auto_reconcile / commission_rate 等）
  async updateConfig(payload) {
    const res = await http.patch('/admin/reconcile/config', payload)
    return res.data
  },
  // 历史报告（90 天）
  async listReports(params = {}) {
    const res = await http.get('/admin/reconcile/reports', { params })
    return res.data
  },
  // 单个报告
  async getReport(id) {
    const res = await http.get(`/admin/reconcile/reports/${id}`)
    return res.data
  }
}

// 交易时段管理
export const sessionApi = {
  async get() {
    const res = await http.get('/admin/trading-session')
    return res.data
  },
  async update(payload) {
    const res = await http.patch('/admin/trading-session', payload)
    return res.data
  }
}

// 费率配置
export const feeConfigApi = {
  async get() {
    const res = await http.get('/fee-config')
    return res.data
  },
  async update(payload) {
    const res = await http.patch('/fee-config', payload)
    return res.data
  }
}
