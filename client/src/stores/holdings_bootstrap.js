/**
 * holdings_bootstrap.js — 持仓 store bootstrap/refresh 流程编排
 *
 * 职责：
 *   - bootstrap: 拉激活日 → IDB 命中优先 → 并行 RPC → 批量写 IDB → yield → 写 Pinia → 启动 ws
 *   - refreshAll: 并行 4 RPC → bulkSave IDB → yield → 写缓存 + 耗时统计
 *   - refreshPositions / refreshAsset: 单资源刷新（兼容旧 API）
 *
 * idbSyncStatus 状态流:
 *   idle → syncing → ready | error
 *   表格组件 v-if="idbSyncStatus.xxx !== 'syncing'" 控制显示
 *
 * 调用者：holdings.js 内 `createBootstrap({...})` 拿 4 个流程函数。
 */
import { api } from '../api'
import { shiftDateStr } from '../utils/date'
import { watch } from 'vue'
import { parseAsset } from './holdings_helpers'
import {
  applyAssetResult, applyPositionsResult, applyOrdersResult, applyTradesResult,
  applyAssetRefresh, applyPositionsRefresh, applyOrdersRefresh, applyTradesRefresh,
  fillTradesDirection,
  _mergeOrders, _mergeTrades,
} from './holdings_apply_results'
import {
  initIDB,
  loadAllOrders,
  loadAllTrades,
  loadAllPositions,
  saveOrder, saveTrade, savePosition,
  clearDate,
  clearAll,
  bulkSave,
} from './holdings_idb'
import { useT0Stats } from '../composables/useT0Stats'
import { useQuoteStore } from './quote'

const BOOTSTRAP_WINDOW_DAYS = 30

/**
 * 创建 bootstrap/refresh 流程工厂
 */
export function createBootstrap({
  positions, orders, trades, cachedAsset,
  activeTrdDate, activeDayStatus,
  refCounts, loading, bootstrapped, lastUpdated,
  idbSyncStatus, log,
  // change init-push-gate: bootstrap/refreshAll 完成兜底关丢弃门 (清 stuck gate)
  initializing,
}) {
  const refs = { positions, orders, trades, cachedAsset, refCounts, idbSyncStatus, log }

  // ---- quote 自动订阅: 只要持仓涉及的标的, 都订阅行情 ----
  // holdings-auto-sub-batch: 持仓去重后 > FULL_MARKET_THRESHOLD 时切 '' 全市场订阅一次,
  //   已全市场订阅则跳过逐只增量 (broker 重连全量推时避免 2197 条 +1 刷屏日志)
  const FULL_MARKET_THRESHOLD = 100
  let _lastSubscribedCodes = []
  let _fullMarketSubscribed = false
  function _syncQuoteSubs(newPositions) {
    const codes = (Array.isArray(newPositions) ? newPositions : [])
      .map(p => p?.stock_code)
      .filter(Boolean)
    const codeSet = [...new Set(codes)]

    // 持仓 > 阈值 → '' 全市场订阅一次; 已订阅直接 return (不再逐只增量/刷日志)
    if (codeSet.length > FULL_MARKET_THRESHOLD) {
      if (!_fullMarketSubscribed) {
        _fullMarketSubscribed = true
        _lastSubscribedCodes = codeSet
        try {
          const qs = useQuoteStore()
          qs.subscribe(codeSet)  // quote.js 内部 >100 → [''] 全市场
          log('ok', '行情', 'auto-sub', `持仓 ${codeSet.length} 只 > ${FULL_MARKET_THRESHOLD}, 切全市场订阅 ('' 一次)`)
        } catch (e) {
          log('warn', '行情', 'auto-sub', `quote subscribe 异常: ${e?.message || e}`)
        }
      }
      return
    }

    // 持仓缩回 ≤ 阈值 → 退出全市场模式, 恢复逐只增量
    if (_fullMarketSubscribed) {
      _fullMarketSubscribed = false
      _lastSubscribedCodes = []
    }

    const lastSet = new Set(_lastSubscribedCodes)
    const added = codeSet.filter(c => !lastSet.has(c))
    const removedNotInPos = _lastSubscribedCodes.filter(c => !codeSet.includes(c))
    if (added.length === 0 && removedNotInPos.length === 0) return
    _lastSubscribedCodes = codeSet
    try {
      const qs = useQuoteStore()
      if (added.length) qs.subscribe(added)
      if (removedNotInPos.length) {
        log('info', '行情', 'auto-sub', `持仓减仓但保留订阅: ${removedNotInPos.length}`, { removedNotInPos })
      }
      if (added.length) {
        log('info', '行情', 'auto-sub', `持仓订阅增量: +${added.length}`, { added, total: codeSet.length })
      }
    } catch (e) {
      log('warn', '行情', 'auto-sub', `quote subscribe 异常: ${e?.message || e}`)
    }
  }
  let _stopQuoteWatch = null
  function _startQuoteAutoSub() {
    if (_stopQuoteWatch) return
    _stopQuoteWatch = watch(
      () => (positions.value || []).map(p => p?.stock_code).filter(Boolean),
      (newCodes) => _syncQuoteSubs((positions.value || [])),
      { immediate: false }
    )
    if (bootstrapped.value) {
      _syncQuoteSubs(positions.value || [])
    }
  }
  function _stopQuoteAutoSub() {
    if (_stopQuoteWatch) { _stopQuoteWatch(); _stopQuoteWatch = null }
  }

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
   * bootstrap: App 启动 / 登录后调用
   *   1) 拉激活日
   *   2) IDB 命中 → 读 IDB 写 Pinia → 设 ready
   *   3) IDB miss → RPC 4路拉取 → bulkWrite IDB → yield → 写 Pinia → 设 ready
   *   4) 跨日 → clearDate(昨日)
   *   5) 全部 ready 后 → 订阅行情 + WS connect
   */
  async function bootstrap(wsConnect) {
    if (loading.value) return
    loading.value = true
    log('info', '缓存', 'bootstrap', '开始加载账户缓存 (资金 / 持仓 / 委托 / 成交)')
    try {
      await _resolveActiveDay()

      refCounts.value = { asset: 'loading', positions: 'loading', orders: 'loading', trades: 'loading' }
      idbSyncStatus.value = { asset: 'syncing', positions: 'syncing', orders: 'syncing', trades: 'syncing' }

      // ─── IDB 命中优先 ───
      const idbHit = await _tryIDBFirst()

      const useFullPull = !idbHit
      const allQuery = { all: true, limit: 10000 }

      const tasks = [
        api.getAsset().catch((e) => { throw e }),
        api.getHoldings().catch((e) => { throw e }),
      ]
      if (useFullPull) {
        tasks.push(api.getOrders(allQuery).catch((e) => { throw e }))
        tasks.push(api.getTrades(allQuery).catch((e) => { throw e }))
      } else {
        tasks.push(Promise.resolve({ code: 0, list: [] }))
        tasks.push(Promise.resolve({ code: 0, list: [] }))
      }
      const results = await Promise.allSettled(tasks)
      const [rAsset, rPos, rOrd, rTrd] = results

      await applyAssetResult(rAsset, refs, 'bootstrap')
      await applyPositionsResult(rPos, refs, 'bootstrap')

      if (useFullPull) {
        await applyOrdersResult(rOrd, refs, 'bootstrap')
        await applyTradesResult(rTrd, refs, 'bootstrap')
      } else {
        // IDB hit: orders/trades 已由 _tryIDBFirst 写入 + status 一致翻牌,
        // 此处只留日志 (旧版此处冗余设 idbSyncStatus, 现统一下沉到 _tryIDBFirst)
        log('info', '缓存', 'bootstrap', 'IDB hit, 跳过 RPC orders/trades')
      }

      bootstrapped.value = true
      lastUpdated.value = Date.now()

      // 全部 ready 后 → 订阅行情 + WS connect
      const allReady = Object.values(idbSyncStatus.value).every(s => s === 'ready')
      if (allReady) {
        _syncQuoteSubs(positions.value || [])
      }

      // 启动 ws
      if (typeof wsConnect === 'function') wsConnect()
      log('info', '缓存', 'bootstrap', 'WS 已连接, 启动实时订阅')
    } catch (e) {
      log('err', '缓存', 'bootstrap', 'bootstrap 异常', String(e?.message || e))
      idbSyncStatus.value = { asset: 'error', positions: 'error', orders: 'error', trades: 'error' }
    } finally {
      loading.value = false
      // change init-push-gate: bootstrap 结束兜底关丢弃门 (日初 resetForNewDay → bootstrap 时自动清 gate)
      initializing.value = false
    }
  }

  /**
   * 尝试从 IDB 同步读回 orders / trades / positions。
   * @returns {Promise<boolean>} 是否 IDB hit
   */
  async function _tryIDBFirst() {
    if (!activeTrdDate.value) return false
    try {
      await initIDB()
      const [cachedOrders, cachedTrades, cachedPositions] = await Promise.all([
        loadAllOrders(),
        loadAllTrades(),
        loadAllPositions(),
      ])

      // 全 miss → 走 RPC fallback
      if (!cachedOrders && !cachedTrades && !cachedPositions) {
        log('info', '缓存', 'idb', `IDB miss → 走 RPC 全量拉`)
        return false
      }

      // 有任一命中: 写 Pinia + 统一翻 status (orders / trades / positions 三 store 一致处理)
      //   - IDB 有数据 → 用 IDB 数据; 无数据 (loadXxxAll 返 null) → 设空数组
      //   - refCounts / idbSyncStatus 一律 'ok' / 'ready' (IDB 已成功读, 不论该 store 是否空, 都视为有效结果)
      //   - 修复 (fix-trades-loading-status-stuck): 旧版只在 length>0 时翻牌, 部分命中场景
      //     (trades 表空 + orders/positions 有) 会让 trades 卡 'loading' 永不翻牌 → UI "成交 加载中" 永远不消失.
      orders.value = cachedOrders || []
      refCounts.value.orders = 'ok'
      idbSyncStatus.value.orders = 'ready'

      trades.value = cachedTrades || []
      refCounts.value.trades = 'ok'
      idbSyncStatus.value.trades = 'ready'

      positions.value = cachedPositions || []
      refCounts.value.positions = 'ok'
      idbSyncStatus.value.positions = 'ready'

      const oLen = cachedOrders?.length ?? 0
      const tLen = cachedTrades?.length ?? 0
      const pLen = cachedPositions?.length ?? 0
      log('info', '缓存', 'idb',
        `IDB 命中 (orders=${oLen}, trades=${tLen}, positions=${pLen}) — 跳过 RPC 全量拉`)
      return true
    } catch (e) {
      log('warn', '缓存', 'idb', `IDB 读失败 (降级走 RPC): ${e?.message || e}`)
      return false
    }
  }

  /**
   * bootstrap / refreshAll 完成后 fire-and-forget 写 IDB (positions 用 savePosition)。
   */
  function _saveAfterBootstrap() {
    if (!activeTrdDate.value) return
    if (orders.value.length === 0 && trades.value.length === 0 && positions.value.length === 0) return
    for (const order of orders.value) saveOrder(order)
    for (const trade of trades.value) saveTrade(trade)
    for (const pos of positions.value) savePosition(pos)
  }

  /**
   * "刷新数据" 按钮调用：清空 IDB → 全量拉后端 → bulkSave IDB → 写 Pinia
   */
  async function refreshAll() {
    if (loading.value) {
      log('warn', '用户', 'user', '刷新请求被忽略: 已有加载任务进行中')
      return
    }
    loading.value = true
    const t0 = Date.now()
    log('info', '用户', 'user', '刷新数据: 清空缓存 + 全量拉取资金/持仓/委托/成交')

    // 设 syncing 状态（表格 v-if 隐藏）
    idbSyncStatus.value = { asset: 'syncing', positions: 'syncing', orders: 'syncing', trades: 'syncing' }
    refCounts.value = { asset: 'loading', positions: 'loading', orders: 'loading', trades: 'loading' }

    try {
      // 1) 清空 IDB
      await clearAll()

      // 2) 全量拉取
      const allQuery = { all: true, limit: 10000 }
      const results = await Promise.allSettled([
        api.getAsset().catch((e) => { throw e }),
        api.getHoldings().catch((e) => { throw e }),
        api.getOrders(allQuery).catch((e) => { throw e }),
        api.getTrades(allQuery).catch((e) => { throw e })
      ])
      const [rAsset, rPos, rOrd, rTrd] = results

      // 3) apply: IDB bulkSave → yield → Pinia → idbSyncStatus=ready
      const assetSummary = await applyAssetRefresh(rAsset, refs)
      const posSummary = await applyPositionsRefresh(rPos, refs)
      const orderSummary = await applyOrdersRefresh(rOrd, refs)
      const tradeSummary = await applyTradesRefresh(rTrd, refs)

      // 4) 同步行情订阅
      _syncQuoteSubs(positions.value || [])

      lastUpdated.value = Date.now()
      const summary = [assetSummary, posSummary, orderSummary, tradeSummary].filter(Boolean)
      const dt = Date.now() - t0
      log('ok', '用户', 'user', `刷新完成 (${dt}ms): ${summary.join(' / ')}`)
    } catch (e) {
      log('err', '用户', 'user', '刷新异常', String(e?.message || e))
      idbSyncStatus.value = { asset: 'error', positions: 'error', orders: 'error', trades: 'error' }
    } finally {
      loading.value = false
      // change init-push-gate: 手动刷新结束兜底关丢弃门 (清 stuck gate)
      initializing.value = false
    }
  }

  // 兼容旧 API
  async function refreshPositions() {
    refCounts.value.positions = 'loading'
    idbSyncStatus.value.positions = 'syncing'
    try {
      const list = await api.getHoldings()
      const raw = Array.isArray(list) ? list : []
      await bulkSave('positions', raw)
      await new Promise(r => setTimeout(r, 0))
      positions.value = raw
      _syncQuoteSubs(positions.value || [])
      refCounts.value.positions = 'ok'
      idbSyncStatus.value.positions = 'ready'
      lastUpdated.value = Date.now()
      log('ok', '用户', 'user', `持仓已刷新 (${positions.value.length} 只)`)
    } catch (e) {
      refCounts.value.positions = 'fail'
      idbSyncStatus.value.positions = 'error'
      log('err', '缓存', 'rpc', '持仓刷新失败', String(e?.message || e))
    }
  }
  async function refreshAsset() {
    refCounts.value.asset = 'loading'
    idbSyncStatus.value.asset = 'syncing'
    try {
      const a = parseAsset(await api.getAsset())
      if (a) cachedAsset.value = a
      refCounts.value.asset = 'ok'
      idbSyncStatus.value.asset = 'ready'
      lastUpdated.value = Date.now()
      log('ok', '用户', 'user', `资金已刷新 (¥${cachedAsset.value.total_asset.toLocaleString()})`)
    } catch (e) {
      refCounts.value.asset = 'fail'
      idbSyncStatus.value.asset = 'error'
      log('err', '缓存', 'rpc', '资金刷新失败', String(e?.message || e))
    }
  }

  /**
   * 拉取激活交易日（推送守门权威源）
   */
  async function _resolveActiveDay() {
    try {
      const activeList = await api.getActiveDay()
      const active = Array.isArray(activeList) ? activeList[0] : activeList
      if (active && active.status === 'active' && active.trd_date) {
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

  /**
   * 日初成功后 force re-bootstrap
   */
  async function resetForNewDay(wsConnect) {
    log('info', '用户', 'day-init', '日初完成: 切交易日 + force re-bootstrap')
    const prevDay = activeTrdDate.value
    try {
      if (prevDay) {
        await clearDate(prevDay)
        log('info', '缓存', 'idb', `clearDate(${prevDay}) 完成 (避免新日 IDB 命中陈旧)`)
      }
    } catch (e) {
      log('warn', '缓存', 'idb', `clearDate 失败 (降级): ${e?.message || e}`)
    }
    positions.value = []
    orders.value = []
    trades.value = []
    cachedAsset.value = { cash: 0, frozen_cash: 0, market_value: 0, total_asset: 0 }
    refCounts.value = { asset: 'idle', positions: 'idle', orders: 'idle', trades: 'idle' }
    idbSyncStatus.value = { asset: 'idle', positions: 'idle', orders: 'idle', trades: 'idle' }
    bootstrapped.value = false
    loading.value = false
    lastUpdated.value = 0
    return bootstrap(wsConnect)
  }

  return {
    bootstrap, refreshAll, refreshPositions, refreshAsset,
    _startQuoteAutoSub, _stopQuoteAutoSub, _syncQuoteSubs,
    resetForNewDay,
  }
}
