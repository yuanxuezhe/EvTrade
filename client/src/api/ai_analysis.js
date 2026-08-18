// ai_analysis.js - AI 分析 API client
// 调 /api/ai/ai-analysis，返回 {code, msg, report, table_rows, synthesis, elapsed_sec, disclaimer}
import { http } from './index'

export const aiAnalysisApi = {
  /**
   * 同步 PoC：调后端 → 后端 subprocess.run invest-analyst demo 脚本
   * @param {Object} params
   * @param {string} params.stockCode  "159992.SZ"
   * @param {string[]} params.periods  ["1d","4h","1h","30m"]
   * @param {string} params.startDate  "20240813"
   * @param {string} params.endDate    "20260812"
   * @returns {Promise<{code, msg, report, table_rows, synthesis, elapsed_sec, disclaimer}>}
   */
  async analyze({ stockCode, periods, startDate, endDate }) {
    const body = {
      stock_code: stockCode,
      periods: periods,
      start_date: startDate,
      end_date: endDate,
    }
    // 同步 PoC: 60-180s, axios 默认 15s 超时不够
    const res = await http.post('/ai/ai-analysis', body, { timeout: 300_000 })
    return res.data
  },
}
