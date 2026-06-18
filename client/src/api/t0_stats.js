import { http } from './index'

/**
 * T0 收益统计 API
 * GET /api/orders/t0-stats/{stock_code}?trd_date=YYYYMMDD&t0_only=true
 * GET /api/orders/t0-history/{stock_code}?days=30&t0_only=true
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
}
