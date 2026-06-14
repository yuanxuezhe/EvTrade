import { http } from './index'

/**
 * T0 收益统计 API
 * GET /api/orders/t0-stats/{stock_code}?trading_day=YYYYMMDD
 */
export const t0StatsApi = {
  /**
   * 获取 T0 当日 / 历史收益汇总
   * @param {string} stockCode
   * @param {string} [tradingDay] - 8 位数字 YYYYMMDD
   */
  async get(stockCode, tradingDay) {
    const params = tradingDay ? { trading_day: tradingDay } : {}
    const { data } = await http.get(`/api/orders/t0-stats/${stockCode}`, { params })
    return data
  }
}
