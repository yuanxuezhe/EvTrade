/**
 * holdings_bootstrap.js — 持仓 store bootstrap/refresh 流程编排
 *
 * phase-3 抽取：把 bootstrap/refreshAll/refreshPositions/refreshAsset
 * 4 个流程编排从 holdings.js 拆出，保持 holdings.js 单 store facade (R3)。
 *
 * 单资源结果应用 helper 已下沉到 holdings_apply_results.js（避免本文件超 250 行）。
 *
 * 职责：
 *   - bootstrap: 拉激活日 → 并行 4 RPC → 启动 ws
 *   - refreshAll: 并行 4 RPC → 写缓存 + 耗时统计
 *   - refreshPositions / refreshAsset: 单资源刷新（兼容旧 API）
 *
 * 调用者：holdings.js 内 `createBootstrap({...})` 拿 4 个流程函数。
 */
import { api } from '../api'
import { shiftDateStr } from '../utils/date'
import { parseAsset } from './holdings_helpers'
import {
  applyAssetResult, applyPositionsResult, applyOrdersResult, applyTradesResult,
  applyAssetRefresh, applyPositionsRefresh, applyOrdersRefresh, applyTradesRefresh,
} from './holdings_apply_results'

// v9: bootstrap 拉 30 天窗口全量委托/成交缓存（满足 30 天回看需求）
// 单次激活日窗口 (bootstrap-window) = [active-29, active]，含当天共 30 天
const BOOTSTRAP_WINDOW_DAYS = 30

/**
 * 创建 bootstrap/refresh 流程工厂
 *
 * @param {Object} deps
 * @param {Ref<Array>}  deps.positions
 * @param {Ref<Array>}  deps.orders
 * @param {Ref<Array>}  deps.trades
 * @param {Ref<Object>} deps.cachedAsset
 * @param {Ref<string>} deps.activeTrdDate
 * @param {Ref<string>} deps.activeDayStatus
 * @param {Ref<Object>} deps.refCounts
 * @param {Ref<boolean>} deps.loading
 * @param {Ref<boolean>} deps.bootstrapped
 * @param {Ref<number>} deps.lastUpdated
 * @param {Function}    deps.log         log(level, tag, source, message, detail?)
 * @returns {{bootstrap, refreshAll, refreshPositions, refreshAsset}}
 */
export function createBootstrap({
  positions, orders, trades, cachedAsset,
  activeTrdDate, activeDayStatus,
  refCounts, loading, bootstrapped, lastUpdated,
  log,
}) {
  const refs = { positions, orders, trades, cachedAsset, refCounts, log }

  /**
   * 计算 bootstrap 用的 30 天窗口 { startDate, endDate }
   *   - 终边 = activeTrdDate.value（v8 推送守门权威源）
   *   - 起始 = shiftDateStr(endDate, -(BOOTSTRAP_WINDOW_DAYS-1))  ← 含当天共 30 天
   *   - activeTrdDate 未就绪（仍为 null）时返 { undefined, undefined }，
   *     让 api.getOrders/getTrades 走无参老路径，避免给后端发畸形日期
   *   - shiftDateStr 抛错时降级为 { undefined, endDate }（单日窗口）
   */
  function _buildWindow() {
    const endDate = activeTrdDate.value
    if (!endDate) {
      return { startDate: undefined, endDate: undefined }
    }
    try {
      const startDate = shiftDateStr(endDate, -(BOOTSTRAP_WINDOW_DAYS - 1))
      return { startDate, endDate }
    } catch (e) {
      log('warn', '缓存', 'bootstrap', 'shiftDateStr 失败, 回退单日窗口', String(e?.message || e))
      return { startDate: undefined, endDate }
    }
  }

  /**
   * App 启动 / 登录后调用：
   *   1) 先拉激活日 (api.getActiveDay) → 写 activeTrdDate (v8: 推送守门用)
   *   2) 并行拉 4 个 RPC（asset / holdings / orders / trades）→ 写缓存 → 写日志
   *   3) 启动 ws + 实时市值 watcher
   */
  async function bootstrap(wsConnect) {
    if (loading.value) return
    loading.value = true
    log('info', '缓存', 'bootstrap', '开始加载账户缓存 (资金 / 持仓 / 委托 / 成交)')
    try {
      await _resolveActiveDay()

      refCounts.value = { asset: 'loading', positions: 'loading', orders: 'loading', trades: 'loading' }

      const dateRange = _buildWindow()
      const results = await Promise.allSettled([
        api.getAsset().catch((e) => { throw e }),
        api.getHoldings().catch((e) => { throw e }),
        api.getOrders(dateRange).catch((e) => { throw e }),
        api.getTrades(dateRange).catch((e) => { throw e })
      ])
      const [rAsset, rPos, rOrd, rTrd] = results

      applyAssetResult(rAsset, refs, 'bootstrap')
      applyPositionsResult(rPos, refs, 'bootstrap')
      applyOrdersResult(rOrd, refs, 'bootstrap')
      applyTradesResult(rTrd, refs, 'bootstrap')

      bootstrapped.value = true
      lastUpdated.value = Date.now()

      // 启动 ws（回调由 holdings.js 注入，避免循环依赖）
      if (typeof wsConnect === 'function') wsConnect()
      log('info', '缓存', 'bootstrap', 'WS 已连接, 启动实时订阅')
    } catch (e) {
      log('err', '缓存', 'bootstrap', 'bootstrap 异常', String(e?.message || e))
    } finally {
      loading.value = false
    }
  }

  /**
   * "刷新数据" 按钮调用：重拉 4 个 RPC，并行 + 写日志 + 统计耗时
   */
  async function refreshAll() {
    if (loading.value) {
      log('warn', '用户', 'user', '刷新请求被忽略: 已有加载任务进行中')
      return
    }
    loading.value = true
    const t0 = Date.now()
    log('info', '用户', 'user', '刷新数据: 重新拉取资金 / 持仓 / 委托 / 成交')
    try {
      refCounts.value = { asset: 'loading', positions: 'loading', orders: 'loading', trades: 'loading' }

      const dateRange = _buildWindow()
      const results = await Promise.allSettled([
        api.getAsset().catch((e) => { throw e }),
        api.getHoldings().catch((e) => { throw e }),
        api.getOrders(dateRange).catch((e) => { throw e }),
        api.getTrades(dateRange).catch((e) => { throw e })
      ])
      const [rAsset, rPos, rOrd, rTrd] = results

      const summary = [
        applyAssetRefresh(rAsset, refs),
        applyPositionsRefresh(rPos, refs),
        applyOrdersRefresh(rOrd, refs),
        applyTradesRefresh(rTrd, refs),
      ].filter(Boolean)

      lastUpdated.value = Date.now()
      const dt = Date.now() - t0
      log('ok', '用户', 'user', `刷新完成 (${dt}ms): ${summary.join(' / ')}`)
    } catch (e) {
      log('err', '用户', 'user', '刷新异常', String(e?.message || e))
    } finally {
      loading.value = false
    }
  }

  // 兼容旧 API（其它 view 还在调用）
  async function refreshPositions() {
    refCounts.value.positions = 'loading'
    try {
      const list = await api.getHoldings()
      positions.value = Array.isArray(list) ? list : []
      refCounts.value.positions = 'ok'
      lastUpdated.value = Date.now()
      log('ok', '用户', 'user', `持仓已刷新 (${positions.value.length} 只)`)
    } catch (e) {
      refCounts.value.positions = 'fail'
      log('err', '缓存', 'rpc', '持仓刷新失败', String(e?.message || e))
    }
  }
  async function refreshAsset() {
    refCounts.value.asset = 'loading'
    try {
      const a = parseAsset(await api.getAsset())
      if (a) cachedAsset.value = a
      refCounts.value.asset = 'ok'
      lastUpdated.value = Date.now()
      log('ok', '用户', 'user', `资金已刷新 (¥${cachedAsset.value.total_asset.toLocaleString()})`)
    } catch (e) {
      refCounts.value.asset = 'fail'
      log('err', '缓存', 'rpc', '资金刷新失败', String(e?.message || e))
    }
  }

  /**
   * 拉取激活交易日（v8: 推送守门权威源）
   * 失败不中断 bootstrap，降级为 activeTrdDate=null（applyXxx 守门放行）
   */
  async function _resolveActiveDay() {
    try {
      const activeList = await api.getActiveDay()
      const active = Array.isArray(activeList) ? activeList[0] : activeList
      if (active && active.status === 'active' && active.trd_date) {
        activeTrdDate.value = active.trd_date
        activeDayStatus.value = 'active'
        log('ok', '缓存', 'bootstrap', `激活交易日 = ${active.trd_date}`)
      } else {
        activeTrdDate.value = null
        activeDayStatus.value = active?.status || 'inactive'
        log('warn', '缓存', 'bootstrap', `未激活交易日 (status=${active?.status || '?'}),推送守门降级`)
      }
    } catch (e) {
      activeTrdDate.value = null
      activeDayStatus.value = null
      log('warn', '缓存', 'rpc', '激活日拉取失败,推送守门降级', String(e?.message || e))
    }
  }

  return { bootstrap, refreshAll, refreshPositions, refreshAsset }
}