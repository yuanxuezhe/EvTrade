import { defineStore } from 'pinia'
import { ref, watch } from 'vue'
import { api } from '../api'
import { useQuoteStore } from './quote'
import { useAssetStore } from './asset'
import { useWsStore } from './ws'
import { bulkReplace, touchLastWrite } from '../utils/idbStore'

// phase-2 拆分: 保持单 Pinia store facade (R3 reactivity 陷阱), 抽出 4 个无状态 helper 模块
import { createLogger } from './holdings_log'
import { parseAsset, recomputeStatus } from './holdings_helpers'
import { createMarketComputeds } from './holdings_market'
import { createPushHandlers } from './holdings_push'

/**
 * 持仓 + 资金 + 委托 + 成交 + 实时行情  全局缓存中心
 *
 * 职责：
 *   1. App 启动 / 登录成功后，bootstrap() 一次性拉取 4 个核心数据
 *        - asset (资金) / positions (持仓) / orders (委托) / trades (成交)
 *      全部来自后端 REST RPC（api.js 拦截器已自动解包 {code,msg,list}）
 *   2. 启动 ws（order_update / trade_update / position_update / asset_update / quote_update）
 *   3. 持仓中的代码才把行情写进 quote store（按 stock_code 白名单过滤）
 *   4. 行情变动时实时重算 market_value，并写回 asset store
 *   5. 操作历史 loadHistory：记录所有缓存加载结果 + 用户主动操作
 *      渲染在 OperationLog 组件（页面底部）
 *   6. ws 推送的 pos_cfm / ast_cfm / ord_cfm / trd_cfm 也通过 applyXxx 走相同路径
 *      保证缓存一致性
 *
 * 视图层约定（21 view 不变）：
 *   - 仪表盘 / 委托 / 成交 / 持仓 / 资金 全部从 holdings store 读，无需各自 onMounted fetch
 *   - 刷新数据按钮（AppHeader）→ holdingsStore.refreshAll()
 *   - ws 推送到时由 ws.js 调用 applyXxx，写日志
 *
 * phase-2 模块边界：
 *   - holdings_log.js     — log/clearHistory + MAX_HISTORY
 *   - holdings_helpers.js — parseAsset / recomputeStatus / nowHMS / todayYYYYMMDD（纯函数）
 *   - holdings_market.js  — liveMarketValue / liveTotalAsset / positionCodes / getXxx（computed 工厂）
 *   - holdings_push.js    — applyXxx ws 推送 5 入口（factory）
 *   - holdings.js (本文件) — Pinia store facade 装配 + bootstrap/refreshAll
 */
export const useHoldingsStore = defineStore('holdings', () => {
  // ---- 基础缓存 --------------------------------------------------------
  const positions = ref([])          // 后端 holdings 接口原始 6 字段
  const orders = ref([])             // 后端 orders
  const trades = ref([])             // 后端 trades
  const cachedAsset = ref({         // 后端 asset 接口初值
    cash: 0, frozen_cash: 0, market_value: 0, total_asset: 0
  })

  // ---- v8: 激活交易日权威源 -----------------------------------------
  //   后端 push 链路已强制覆盖 trd_date = activeTrdDate
  //   前端守门: applyOrderPush/applyTradePush 必须按 (activeTrdDate, order_no) 匹配
  //   - null: bootstrap 失败 / 未做日初 → 降级放行(不崩),但 log 警告
  const activeTrdDate = ref(null)   // 8 位 YYYYMMDD 或 null
  const activeDayStatus = ref(null) // 'active' | 'inactive' | null

  // ---- 运行时状态 -----------------------------------------------------
  const loading = ref(false)         // bootstrap / refresh 中
  const bootstrapped = ref(false)    // 至少 bootstrap 过一次
  const lastUpdated = ref(0)         // 上次刷新的 ms 时间戳
  const refCounts = ref({           // 4 个资源各自独立的加载状态
    asset: 'idle', positions: 'idle', orders: 'idle', trades: 'idle'
  })  // 'idle' | 'loading' | 'ok' | 'fail'

  // ---- 操作流水（页面底部显示） ---------------------------------------
  // 每条: { id, ts, level, tag, source, message, detail? }
  //   tag    - 大类筛选标签: '缓存' | '交易' | '用户' | '系统'
  //   source - 细分类: 'bootstrap' / 'refresh' / 'ws' / 'user' / 'rpc'
  const loadHistory = ref([])
  const { log, clearHistory } = createLogger(loadHistory)

  // ---- 计算（实时）+ getters ------------------------------------------
  const {
    liveMarketValue, liveTotalAsset, positionCodes,
    getLivePrice, getMarketValue, getProfit, getReturnRate,
  } = createMarketComputeds(positions, cachedAsset, () => useQuoteStore())

  // ---- ws 推送入口（ws.js 调） ----------------------------------------
  const {
    applyPositionPush, applyAssetPush, applyOrderPush, applyTradePush, applyQuote,
  } = createPushHandlers({
    positions, orders, trades, cachedAsset, activeTrdDate,
    log, positionCodes, getQuoteStore: () => useQuoteStore(),
  })

  // ---- 启动 / 刷新 ----------------------------------------------------

  /**
   * App 启动 / 登录后调用：
   *   1) 先拉激活日 (api.getActiveDay) → 写 activeTrdDate (v8: 推送守门用)
   *   2) 并行拉 4 个 RPC（asset / holdings / orders / trades）→ 写缓存 → 写日志
   *   3) 启动 ws + 实时市值 watcher
   */
  async function bootstrap() {
    if (loading.value) return
    loading.value = true
    log('info', '缓存', 'bootstrap', '开始加载账户缓存 (资金 / 持仓 / 委托 / 成交)')
    try {
      // v8: 先拉激活交易日（推送守门权威源）
      //   失败不中断 bootstrap，降级为 activeTrdDate=null（applyXxx 守门放行）
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

      refCounts.value = { asset: 'loading', positions: 'loading', orders: 'loading', trades: 'loading' }

      const results = await Promise.allSettled([
        api.getAsset().catch((e) => { throw e }),
        api.getHoldings().catch((e) => { throw e }),
        api.getOrders().catch((e) => { throw e }),
        api.getTrades().catch((e) => { throw e })
      ])
      const [rAsset, rPos, rOrd, rTrd] = results

      // asset
      if (rAsset.status === 'fulfilled') {
        const a = parseAsset(rAsset.value)
        if (a) cachedAsset.value = a
        refCounts.value.asset = 'ok'
        log('ok', '缓存', 'bootstrap', `资金加载成功 (¥${(a?.total_asset || 0).toLocaleString()})`)
      } else {
        refCounts.value.asset = 'fail'
        log('err', '缓存', 'rpc', '资金加载失败', String(rAsset.reason?.message || rAsset.reason))
      }
      // positions
      if (rPos.status === 'fulfilled') {
        // 后端返 {code:0, list:[...]}，解 .list
        positions.value = Array.isArray(rPos.value) ? rPos.value
          : (Array.isArray(rPos.value?.list) ? rPos.value.list : [])
        refCounts.value.positions = 'ok'
        log('ok', '缓存', 'bootstrap', `持仓加载成功 (${positions.value.length} 只)`)
      } else {
        refCounts.value.positions = 'fail'
        log('err', '缓存', 'rpc', '持仓加载失败', String(rPos.reason?.message || rPos.reason))
      }
      // orders（v8: 防御性 status 重算 —— 不信任后端推的 status 字段）
      if (rOrd.status === 'fulfilled') {
        const rawOrders = Array.isArray(rOrd.value) ? rOrd.value
          : (Array.isArray(rOrd.value?.list) ? rOrd.value.list : [])
        orders.value = rawOrders.map(recomputeStatus)
        refCounts.value.orders = 'ok'
        log('ok', '缓存', 'bootstrap', `委托加载成功 (${orders.value.length} 条)`)
      } else {
        refCounts.value.orders = 'fail'
        log('err', '缓存', 'rpc', '委托加载失败', String(rOrd.reason?.message || rOrd.reason))
      }
      // trades
      if (rTrd.status === 'fulfilled') {
        trades.value = Array.isArray(rTrd.value) ? rTrd.value
          : (Array.isArray(rTrd.value?.list) ? rTrd.value.list : [])
        refCounts.value.trades = 'ok'
        log('ok', '缓存', 'bootstrap', `成交加载成功 (${trades.value.length} 条)`)
      } else {
        refCounts.value.trades = 'fail'
        log('err', '缓存', 'rpc', '成交加载失败', String(rTrd.reason?.message || rTrd.reason))
      }

      bootstrapped.value = true
      lastUpdated.value = Date.now()

      // write-through 委托 + 成交 表 (持仓由 position.js fetchPositions 写, 资金由 asset.js fetchAsset 写)
      try {
        await bulkReplace('orders', orders.value)
        await bulkReplace('trades', trades.value)
        await touchLastWrite()
      } catch (e) {
        console.warn('[holdings] IDB write-through 失败:', e)
      }

      // 启动 ws
      const ws = useWsStore()
      ws.connect()
      log('info', '缓存', 'bootstrap', 'WS 已连接, 启动实时订阅')
    } catch (e) {
      log('err', '缓存', 'bootstrap', 'bootstrap 异常', String(e?.message || e))
    } finally {
      loading.value = false
    }
  }

  /**
   * "刷新数据" 按钮调用：重拉 4 个 RPC
   * 并行 + 写日志 + 统计耗时
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

      const results = await Promise.allSettled([
        api.getAsset().catch((e) => { throw e }),
        api.getHoldings().catch((e) => { throw e }),
        api.getOrders().catch((e) => { throw e }),
        api.getTrades().catch((e) => { throw e })
      ])
      const [rAsset, rPos, rOrd, rTrd] = results
      const summary = []

      if (rAsset.status === 'fulfilled') {
        const a = parseAsset(rAsset.value)
        if (a) cachedAsset.value = a
        refCounts.value.asset = 'ok'
        summary.push(`资金 ¥${(a?.total_asset || 0).toLocaleString()}`)
      } else {
        refCounts.value.asset = 'fail'
        log('err', '缓存', 'rpc', '资金刷新失败', String(rAsset.reason?.message || rAsset.reason))
      }
      if (rPos.status === 'fulfilled') {
        positions.value = Array.isArray(rPos.value) ? rPos.value : []
        refCounts.value.positions = 'ok'
        summary.push(`持仓 ${positions.value.length} 只`)
      } else {
        refCounts.value.positions = 'fail'
        log('err', '缓存', 'rpc', '持仓刷新失败', String(rPos.reason?.message || rPos.reason))
      }
      if (rOrd.status === 'fulfilled') {
        // v8: 防御性 status 重算 —— 不信任后端推的 status 字段
        const rawOrders = Array.isArray(rOrd.value) ? rOrd.value : []
        orders.value = rawOrders.map(recomputeStatus)
        refCounts.value.orders = 'ok'
        summary.push(`委托 ${orders.value.length} 条`)
      } else {
        refCounts.value.orders = 'fail'
        log('err', '缓存', 'rpc', '委托刷新失败', String(rOrd.reason?.message || rOrd.reason))
      }
      if (rTrd.status === 'fulfilled') {
        trades.value = Array.isArray(rTrd.value) ? rTrd.value : []
        refCounts.value.trades = 'ok'
        summary.push(`成交 ${trades.value.length} 条`)
      } else {
        refCounts.value.trades = 'fail'
        log('err', '缓存', 'rpc', '成交刷新失败', String(rTrd.reason?.message || rTrd.reason))
      }

      lastUpdated.value = Date.now()
      const dt = Date.now() - t0
      log('ok', '用户', 'user', `刷新完成 (${dt}ms): ${summary.join(' / ')}`)

      // write-through 委托 + 成交 表
      try {
        await bulkReplace('orders', orders.value)
        await bulkReplace('trades', trades.value)
        await touchLastWrite()
      } catch (e) {
        console.warn('[holdings.refreshAll] IDB write-through 失败:', e)
      }
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

  // ---- watcher：quote 变 → 写回 asset store + 实时市值 ----------

  let _unwatch = null
  function _startWatchers() {
    if (_unwatch) return
    const a = useAssetStore()
    _unwatch = watch(
      () => liveMarketValue.value.sum,
      (mv) => {
        cachedAsset.value = { ...cachedAsset.value, market_value: mv }
        a.asset = {
          ...a.asset,
          market_value: mv,
          total_asset: liveTotalAsset.value
        }
      },
      { flush: 'post' }
    )
  }
  function _stopWatchers() {
    if (_unwatch) { _unwatch(); _unwatch = null }
  }

  return {
    // state（21 view 直接读, 必须全部暴露）
    positions, orders, trades, cachedAsset,
    loading, bootstrapped, lastUpdated, refCounts,
    loadHistory,
    // v8: 激活交易日权威源（推送守门用）
    activeTrdDate, activeDayStatus,
    // computed
    liveMarketValue, liveTotalAsset, positionCodes,
    // actions
    bootstrap, refreshAll,
    refreshPositions, refreshAsset,
    getLivePrice, getMarketValue, getProfit, getReturnRate,
    applyPositionPush, applyAssetPush, applyOrderPush, applyTradePush, applyQuote,
    log, clearHistory,
    _startWatchers, _stopWatchers
  }
})
