import { http } from './http'

/**
 * T0 收益统计 API
 * GET /api/orders/t0-stats/{stock_code}?trd_date=YYYYMMDD&t0_only=true
 * GET /api/orders/t0-history/{stock_code}?days=30&t0_only=true
 * GET /api/orders/t0-exposure?user_def=T0&trd_date=YYYYMMDD      新增（多标的当日敞口）
 * GET /api/orders/t0-aggregate?user_def=T0&days=30              新增（跨期累计）
 */
export const t0StatsApi = {
  /**
   * 获取 T0 当日 / 历史收益汇总
   * @param {string} stockCode
   * @param {string} [tradingDay] - 8 位数字 YYYYMMDD
   * @param {boolean} [t0Only=false] - 仅统计 T0 标记 (user_def='T0') 的委托/成交
   */
  async get(stockCode, tradingDay, t0Only = false) {
    const params = {}
    if (tradingDay) params.trd_date = tradingDay
    if (t0Only) params.t0_only = true
    const { data } = await http.get(`/orders/t0-stats/${stockCode}`, { params })
    return data
  },
  /**
   * 获取 T0 历史曲线（近 N 天每日已实现）
   * @param {string} stockCode
   * @param {number} [days=30]
   * @param {boolean} [t0Only=false]
   */
  async getHistory(stockCode, days = 30, t0Only = false) {
    const params = { days }
    if (t0Only) params.t0_only = true
    const { data } = await http.get(`/orders/t0-history/${stockCode}`, {
      params,
    })
    return data
  },
  /**
   * 多标的当日敞口聚合（按 user_def 标签）
   * @param {Object} [opts]
   * @param {string} [opts.userDef='T0'] - 标签键（空字符串=全部）
   * @param {string} [opts.trdDate] - 8 位数字 YYYYMMDD，默认=激活日
   * @returns {Promise<{trd_date, user_def, positions: Array, totals: Object}>}
   */
  async getExposure({ userDef = 'T0', trdDate } = {}) {
    const params = { user_def: userDef }
    if (trdDate) params.trd_date = trdDate
    const { data } = await http.get('/orders/t0-exposure', { params })
    return data
  },
  /**
   * 跨期累计 + 按日/按股双视角 + 胜率/回报率
   * @param {Object} [opts]
   * @param {string} [opts.userDef='T0']
   * @param {number} [opts.days=30] - 回溯天数（1-365）
   * @returns {Promise<{user_def, days, summary: Object, by_day: Array, by_stock: Array}>}
   */
  async getAggregate({ userDef = 'T0', days = 30 } = {}) {
    const { data } = await http.get('/orders/t0-aggregate', {
      params: { user_def: userDef, days },
    })
    return data
  },
}
