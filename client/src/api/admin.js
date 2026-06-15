import { http } from './index'

// ============================================================
// 管理 API（v4 系统初始化 + 对账 + 时段 + 费率）
// 后端路由前缀: /api/admin/*  /api/fee-config
// ============================================================

// 系统状态管理（含交易日）
// v5 schema refactor: trading_day → sys_status
export const sysStatusApi = {
  // 当前激活交易日
  async current() {
    const res = await http.get('/admin/sys-status/active')
    return res.data
  },
  // 列出历史交易日
  async list() {
    const res = await http.get('/admin/sys-status')
    return res.data
  },
  // 触发日初（对账 + 切日）
  async init(trdDate, mode = 'auto') {
    const res = await http.post('/admin/sys-status/init', { trd_date: trdDate, mode })
    return res.data
  },
  // 关闭当前日
  async close() {
    const res = await http.post('/admin/sys-status/close')
    return res.data
  }
}

// 兼容旧调用（SystemInit.vue 等已迁移完成；此处保留 alias 以防漏改）
export const tradingDayApi = sysStatusApi

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
  // 单个报告（v5: 复合主键 (trd_date, mode, created_at)）
  async getReport(trdDate, mode, createdAt) {
    const res = await http.get(
      `/admin/reconcile/reports/${encodeURIComponent(trdDate)}/${encodeURIComponent(mode)}/${encodeURIComponent(createdAt)}`
    )
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
