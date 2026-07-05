/**
 * holdings_bootstrap.js — 持仓 store bootstrap/refresh 流程编排
 *
 * phase-3 抽取：把 bootstrap/refreshAll/refreshPositions/refreshAsset
 * 4 个流程编排从 holdings.js 拆出，保持 holdings.js 单 store facade (R3)。
 *
 * 单资源结果应用 helper 已下沉到 holdings_apply_results.js（避免本文件超 250 行）。
 *
 * 职责：
 *   - bootstrap: 拉激活日 → IDB 命中优先 → 并行 RPC → 启动 ws → IDB 写回
 *   - refreshAll: 并行 4 RPC → 写缓存 + 耗时统计
 *   - refreshPositions / refreshAsset: 单资源刷新（兼容旧 API）
 *
 * v12 (add-manual-adjust-and-history-pages):
 *   - bootstrap: IDB hit 时跳过 orders/trades HTTP 拉取（positions / asset 仍拉 RPC）
 *   - bootstrap: 跨日（IDB.trd_date !== active.trd_date）→ clearDate(昨日)
 *   - bootstrap: 拉完 orders/trades 后 fire-and-forget 写 IDB（缓存下次 reload）
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
import {
  initIDB,
  loadOrdersForDate, loadTradesForDate,
  saveOrder, saveTrade,
  clearDate,
} from './holdings_idb'
import { useT0Stats } from '../composables/useT0Stats'

// v13: bootstrap 只拉激活日 (Today 视图消费), 历史走 Phase 4 History 视图独立 RPC
//   单次窗口 = [active, active], 1 天
//   配套 IDB 复合 key 单行存: 写 = N 次 O(1) idbPut, 读 = prefix 扫描
// v13 trade-page-redesign-v2: 单日窗口即"今日缓存"设计语义 — Trade.vue 内嵌 mini-panel
//   (TodayOrdersPanel / TodayTradesPanel) 客户端再守门 trd_date === activeDay, 与本字段解耦;
//   历史数据由 HistoryOrders.vue / HistoryTrades.vue 独立 RPC 路径承担, 不入此窗口。
const BOOTSTRAP_WINDOW_DAYS = 1

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
   *   v12 (IDB 优先):
   *     1) 拉激活日 (api.getActiveDay) → 写 activeTrdDate (v8: 推送守门用)
   *     2) 尝试 IDB 命中 orders / trades → 写 Pinia（200ms 内显示）
   *     3) IDB 命中时跳过 orders / trades HTTP 拉取；否则并行 4 RPC → 写缓存 → 写日志
   *     4) 跨日 → clearDate(昨日)
   *     5) 拉取完成后 fire-and-forget 写 IDB（缓存下次 reload）
   *     6) 启动 ws + 实时市值 watcher
   */
  async function bootstrap(wsConnect) {
    if (loading.value) return
    loading.value = true
    log('info', '缓存', 'bootstrap', '开始加载账户缓存 (资金 / 持仓 / 委托 / 成交)')
    try {
      await _resolveActiveDay()

      refCounts.value = { asset: 'loading', positions: 'loading', orders: 'loading', trades: 'loading' }

      // ─── v12: IDB 命中优先 ───
      const idbHit = await _tryIDBFirst()

      // build 委托/成交 拉取范围：仅在 IDB miss 时拉 30 天窗口
      const dateRange = idbHit ? null : _buildWindow()

      // v12: IDB hit 时 orders/trades 不发 RPC；asset / positions 仍拉
      const tasks = [
        api.getAsset().catch((e) => { throw e }),
        api.getHoldings().catch((e) => { throw e }),
      ]
      if (dateRange) {
        tasks.push(api.getOrders(dateRange).catch((e) => { throw e }))
        tasks.push(api.getTrades(dateRange).catch((e) => { throw e }))
      } else {
        // IDB hit 时占位 fulfilled（applyOrdersResult / applyTradesResult 不会动 orders / trades）
        tasks.push(Promise.resolve({ code: 0, list: [] }))
        tasks.push(Promise.resolve({ code: 0, list: [] }))
      }
      const results = await Promise.allSettled(tasks)
      const [rAsset, rPos, rOrd, rTrd] = results

      applyAssetResult(rAsset, refs, 'bootstrap')
      applyPositionsResult(rPos, refs, 'bootstrap')
      applyOrdersResult(rOrd, refs, 'bootstrap')
      applyTradesResult(rTrd, refs, 'bootstrap')

      bootstrapped.value = true
      lastUpdated.value = Date.now()

      // ─── v12: 拉取完成后 fire-and-forget 写 IDB ───
      _saveAfterBootstrap()

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
   * v12: 尝试从 IDB 同步读回 orders / trades。
   *   - IDB 命中且 activeDay 一致 → 立刻写 Pinia，返 true（bootstrap 跳过 HTTP 拉取）
   *   - IDB 跨日或不可用 → 返 false（bootstrap 走正常 RPC）
   *   - 跨日 → clearDate(昨日 key)
   * @returns {Promise<boolean>} 是否 IDB hit
   */
  async function _tryIDBFirst() {
    const activeDay = activeTrdDate.value
    if (!activeDay) return false

    try {
      await initIDB()  // 可能 reject（Node / SSR），跳 IDB 路径
      const [cachedOrders, cachedTrades] = await Promise.all([
        loadOrdersForDate(activeDay),
        loadTradesForDate(activeDay),
      ])

      // IDB 跨日检查（防御性：理论上 IDB key 已限定 activeDay，但保留检查）
      // IDB miss 是合法（首次启动 / 新交易日）— 走 RPC fallback 即可
      if (cachedOrders === null && cachedTrades === null) {
        log('info', '缓存', 'idb', `IDB miss for ${activeDay} → 走 RPC`)
        return false
      }

      // 命中：立刻写 Pinia（orders/trades ref 是 readonly interface，写入触发响应）
      if (Array.isArray(cachedOrders)) {
        orders.value = cachedOrders
        refCounts.value.orders = 'ok'
      }
      if (Array.isArray(cachedTrades)) {
        trades.value = cachedTrades
        refCounts.value.trades = 'ok'
      }
      log('info', '缓存', 'idb',
        `IDB 命中 (orders=${cachedOrders?.length ?? 0}, trades=${cachedTrades?.length ?? 0}) — 跳过 RPC 拉取`)
      return true
    } catch (e) {
      // IDB 不可用（隐私模式 / quota）：静默降级
      log('warn', '缓存', 'idb', `IDB 不可用 → 走 RPC: ${e?.message || e}`)
      return false
    }
  }

  /**
   * v13: bootstrap / refreshAll 完成后 fire-and-forget 写 IDB。
   *   - 复合 key 单行存: orders/trades 各 loop saveOrder/saveTrade
   *   - 加空检查 (risk #5 修复): 全空时不写, 避免无意义 IO
   *   - 仅当 activeDay 已 resolve 时写
   */
  function _saveAfterBootstrap() {
    const activeDay = activeTrdDate.value
    if (!activeDay) return
    if (orders.value.length === 0 && trades.value.length === 0) return
    for (const order of orders.value) saveOrder(order)
    for (const trade of trades.value) saveTrade(trade)
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
      // v12: refresh 拉到的 orders / trades 也 fire-and-forget 写 IDB
      _saveAfterBootstrap()
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
        // change t0-trade-polish-bundle (commit 3): 跨日 → 清空 t0Stats 缓存
        //   避免昨日的 today_buy_volume / realized_pnl 命中今日视图
        if (activeTrdDate.value && activeTrdDate.value !== active.trd_date) {
          useT0Stats.invalidateAll()
          log('info', '缓存', 'bootstrap', `跨日切换 ${activeTrdDate.value} → ${active.trd_date}, t0Stats 清空`)
        }
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