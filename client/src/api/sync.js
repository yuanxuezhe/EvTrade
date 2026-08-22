import { http } from './index'

/**
 * sync API 客户端 (stock-info-crawler)
 *
 * 端点：
 * - POST   /api/sync/stocks         启动同步任务 (admin only)
 * - DELETE /api/sync/stocks         停止当前任务 (admin only)
 * - GET    /api/sync/stocks/status  当前任务状态
 */
export const syncApi = {
  /** 启动股票基础信息同步
   * @returns {Promise<{job_id, total, already_existed, message}>}
   */
  async start() {
    const { data } = await http.post('/sync/stocks')
    return data
  },

  /** 停止当前同步任务
   * @returns {Promise<{stopped: boolean, job_id: string, state: string}>}
   */
  async stop() {
    const { data } = await http.delete('/sync/stocks')
    return data
  },

  /** 获取当前同步任务状态
   * @returns {Promise<SyncTaskState|null>}
   *   SyncTaskState = {
   *     job_id, state,           // 'running' | 'completed' | 'failed' | 'stopping' | 'stopped'
   *     total, processed,        // 已处理只数
   *     inserted, updated, skipped, failed,
   *     current_code,            // 当前正在处理的股票代码
   *     eta_sec, started_at, finished_at,
   *     errors: [{stock_code, error, ts}],  // 失败明细
   *   }
   *   返 null = 当前没有任务
   */
  async status() {
    const { data } = await http.get('/sync/stocks/status')
    return data
  }
}