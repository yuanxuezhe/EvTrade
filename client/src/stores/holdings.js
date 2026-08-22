/**
 * holdings.js — 持仓 store Pinia facade（phase-3 拆分）
 *
 * phase-2/3 拆分：保持单 Pinia store facade (R3 reactivity 陷阱)，抽出 5 个无状态 helper 模块
 *   - holdings_log.js       — log/clearHistory + MAX_HISTORY
 *   - holdings_helpers.js   — parseAsset / recomputeStatus / nowHMS / todayYYYYMMDD（纯函数）
 *   - holdings_market.js    — liveMarketValue / liveTotalAsset / positionCodes / getXxx（computed 工厂）
 *   - holdings_push.js      — applyXxx ws 推送 5 入口（factory）
 *   - holdings_bootstrap.js — bootstrap/refreshAll/refreshPositions/refreshAsset（流程编排）
 *   - holdings.js（本文件）  — Pinia store 装配 facade
 *
 * 视图层约定（21 view 不变）：
 *   - 仪表盘 / 委托 / 成交 / 持仓 / 资金 全部从 holdings store 读，无需各自 onMounted fetch
 *   - 刷新数据按钮（AppHeader）→ holdingsStore.refreshAll()
 *   - ws 推送到时由 ws.js 调用 applyXxx，写日志
 */
import { defineStore } from 'pinia'
import { ref, watch } from 'vue'
import { useQuoteStore } from './quote'
import { useWsStore } from './ws'

import { createLogger } from './holdings_log'
import { createMarketComputeds } from './holdings_market'
import { createPushHandlers } from './holdings_push'
import { createBootstrap } from './holdings_bootstrap'
import { createDayPnlRecompute } from './holdings_daypnl'
// 注: 原 IDB write-through 已删除. 当前架构纯 Pinia 内存.

export const useHoldingsStore = defineStore('holdings', () => {
  // ---- 基础缓存 --------------------------------------------------------
  const positions = ref([])          // 后端 holdings 接口原始 6 字段
  const orders = ref([])             // 后端 orders
  const trades = ref([])             // 后端 trades
  const cachedAsset = ref({         // 后端 asset 接口初值
    cash: 0, frozen_cash: 0, market_value: 0, total_asset: 0, last_asset: 0  // last_asset
  })

  // ---- 激活交易日权威源 -----------------------------------------
  const activeTrdDate = ref(null)   // 8 位 YYYYMMDD 或 null
  const activeDayStatus = ref(null) // 'active' | 'inactive' | null

  // ---- 运行时状态 -----------------------------------------------------
  const loading = ref(false)
  const bootstrapped = ref(false)
  const lastUpdated = ref(0)
  const refCounts = ref({
    asset: 'idle', positions: 'idle', orders: 'idle', trades: 'idle'
  })

  // ---- idbSyncStatus: IDB 同步状态指示器 --------------------------------
  //   'idle' → 'syncing' → 'ready' | 'error'
  //   表格组件 v-if="idbSyncStatus.xxx !== 'syncing'" 控制显示
  const idbSyncStatus = ref({
    asset: 'idle', positions: 'idle', orders: 'idle', trades: 'idle'
  })

  // ---- change init-push-gate: 系统初始化中标志 ------------------------------
  //   后端 init_start 广播置 true → init_completed/init_aborted 置 false。
  //   true 期间 ws_dispatch 丢弃 pos/ord/trd 推送 (只计数不刷屏),
  //   避免日初 reconcile 窗口把 broker 洪峰写进 positions/orders/trades 中间态。
  const initializing = ref(false)

  // ---- 操作流水 -------------------------------------------------------
  const loadHistory = ref([])
  const { log, clearHistory } = createLogger(loadHistory)

  // ---- 计算（实时）+ getters ------------------------------------------
  const {
    liveMarketValue, liveTotalAsset, positionCodes,
    getLivePrice, getMarketValue, getProfit, getReturnRate,
  } = createMarketComputeds(positions, cachedAsset, () => useQuoteStore())

  // ---- ws 推送入口（ws.js 调） ----------------------------------------
  // change consolidate-position-data-flow: applyPositionPush / applyAssetPush 已删除
  //   (xtquant broker 不发 pos_cfm / ast_cfm, Position/Asset 状态由 day-init reconcile 覆盖)
  const {
    applyOrderPush, applyTradePush, applyQuote, applyPositionUpdate,
  } = createPushHandlers({
    positions, orders, trades, cachedAsset, activeTrdDate,
    log, positionCodes, getQuoteStore: () => useQuoteStore(),
  })

  // ---- 当日盈亏 recompute（holdings_daypnl.js, 行情推送驱动, 无轮询）----
  const {
    start: startDayPnl, stop: stopDayPnl, refreshDayPnl,
  } = createDayPnlRecompute({ positions, activeTrdDate, trades })

  // ---- bootstrap / refresh 流程（holdings_bootstrap.js） ---------------
  const {
    bootstrap: _bootstrap,
    refreshAll,
    refreshPositions,
    refreshAsset,
    // quote 自动订阅控制
    _startQuoteAutoSub: _autoSubStart,
    _stopQuoteAutoSub: _autoSubStop,
    // 日初成功后 force re-bootstrap (切交易日)
    resetForNewDay: _resetForNewDay,
  } = createBootstrap({
    positions, orders, trades, cachedAsset,
    activeTrdDate, activeDayStatus,
    refCounts, loading, bootstrapped, lastUpdated,
    idbSyncStatus, log,
    // change init-push-gate: bootstrap/refreshAll 完成后兜底关丢弃门 (清 stuck gate)
    initializing,
  })

  // 启动 ws 的回调（避免 holdings_bootstrap.js 反向依赖 ws store）
  function _startWs() {
    const ws = useWsStore()
    ws.connect()
  }
  async function bootstrap() {
    const r = await _bootstrap(_startWs)
    // bootstrap 完成后启动 watch (后续 positions 增量同步)
    _autoSubStart()
    return r
  }

  /**
   * 日初成功后 force re-bootstrap
   *   包装 _resetForNewDay, 注入 ws connect 回调 (bootstrap 内部会再调一次, 幂等)
   *   供 ws_dispatch._onInitCompleted 调
   */
  async function resetForNewDay() {
    return _resetForNewDay(_startWs)
  }

  // ---- watcher：quote 变 → 写回 cachedAsset（实时市值）-------------
  // asset store 是 facade, a.asset 通过 computed 桥接到 cachedAsset,
  //      单一写 cachedAsset 即可, 无需再双写 a.asset
  let _unwatch = null
  function _startWatchers() {
    if (_unwatch) return
    _unwatch = watch(
      () => liveMarketValue.value.sum,
      (mv) => {
        cachedAsset.value = {
          ...cachedAsset.value,
          market_value: mv,
          total_asset: liveTotalAsset.value
        }
      },
      { flush: 'post' }
    )
    // 当日盈亏 recompute 挂进同一生命周期 (行情推送驱动, 无轮询)
    startDayPnl()
  }
  function _stopWatchers() {
    stopDayPnl()
    if (_unwatch) { _unwatch(); _unwatch = null }
  }

  return {
    // state（21 view 直接读, 必须全部暴露）
    positions, orders, trades, cachedAsset,
    loading, bootstrapped, lastUpdated, refCounts, idbSyncStatus,
    // change init-push-gate: 系统初始化中标志 (ws_dispatch 丢弃门读, SystemInit/刷新兜底写)
    initializing,
    loadHistory,
    // 激活交易日权威源（推送守门用）
    activeTrdDate, activeDayStatus,
    // computed
    liveMarketValue, liveTotalAsset, positionCodes,
    // actions
    bootstrap, refreshAll, resetForNewDay,
    refreshPositions, refreshAsset,
    getLivePrice, getMarketValue, getProfit, getReturnRate,
    // 当日盈亏 (recompute 已自动, 手动刷新入口给 AppHeader/测试用)
    refreshDayPnl,
    applyOrderPush, applyTradePush, applyQuote, applyPositionUpdate,
    log, clearHistory,
    _startWatchers, _stopWatchers
  }
})