import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import { api } from '../api'
import { useQuoteStore } from './quote'
import { useAssetStore } from './asset'
import { useWsStore } from './ws'
import { inferOrderStatus } from '../utils/format'

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
 * 视图层约定：
 *   - 仪表盘 / 委托 / 成交 / 持仓 / 资金 全部从 holdings store 读，无需各自 onMounted fetch
 *   - 刷新数据按钮（AppHeader）→ holdingsStore.refreshAll()
 *   - ws 推送到时由 ws.js 调用 applyXxx，写日志
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
  const _MAX_HISTORY = 200          // 上限（环形）
  let _histId = 0

  function log(level, tag, source, message, detail = null) {
    _histId++
    const entry = {
      id: _histId,
      ts: Date.now(),
      level,        // 'info' / 'ok' / 'warn' / 'err'
      tag,          // '缓存' | '交易' | '用户' | '系统'
      source,       // 'bootstrap' / 'refresh' / 'ws' / 'user' / 'rpc'
      message,
      detail
    }
    loadHistory.value.unshift(entry)
    if (loadHistory.value.length > _MAX_HISTORY) {
      loadHistory.value.length = _MAX_HISTORY
    }
    // 同时写一份到 console 便于调试
    const tagStr = `[holdings.${source}/${tag}] ${message}`
    if (level === 'err') console.error(tagStr, detail || '')
    else if (level === 'warn') console.warn(tagStr, detail || '')
    else console.log(tagStr, detail || '')
    return entry
  }

  function clearHistory() {
    loadHistory.value = []
  }

  // ---- 计算（实时） ---------------------------------------------------

  /**
   * 实时持仓市值 = sum(quote.last_price * volume) for all positions
   * 行情未到的标的，按 0 计入（不假装有值）
   */
  const liveMarketValue = computed(() => {
    const q = useQuoteStore()
    let sum = 0
    let withQuote = 0
    for (const p of positions.value) {
      const price = q.getLastPrice(p.stock_code)
      if (price != null) {
        sum += price * (Number(p.volume) || 0)
        withQuote++
      }
    }
    return { sum, withQuote, total: positions.value.length }
  })

  /**
   * 实时总资产 = 现金 + 冻结 + 实时市值
   * 初始值（无 quote 时）= 后端 total_asset
   */
  const liveTotalAsset = computed(() => {
    const a = cachedAsset.value
    const mv = liveMarketValue.value.sum
    const allHaveQuote = liveMarketValue.value.withQuote === liveMarketValue.value.total
      && liveMarketValue.value.total > 0
    if (allHaveQuote) {
      return (Number(a.cash) || 0) + (Number(a.frozen_cash) || 0) + mv
    }
    return a.total_asset || 0
  })

  /** 持仓白名单（代码 Set） */
  const positionCodes = computed(() =>
    new Set(positions.value.map((p) => p.stock_code).filter(Boolean))
  )

  function getLivePrice(code) {
    return useQuoteStore().getLastPrice(code) ?? null
  }
  function getMarketValue(p) {
    const price = getLivePrice(p.stock_code)
    if (price == null) return null
    return price * (Number(p.volume) || 0)
  }
  function getProfit(p) {
    const price = getLivePrice(p.stock_code)
    if (price == null) return null
    const cost = Number(p.cost_price) || 0
    const vol = Number(p.vol) || 0
    if (vol === 0) return 0
    return (price - cost) * vol
  }
  function getReturnRate(p) {
    const profit = getProfit(p)
    const cost = Number(p.cost_price) || 0
    const vol = Number(p.vol) || 0
    const costTotal = cost * vol
    if (profit == null || costTotal === 0) return null
    return profit / costTotal
  }

  // ---- 内部辅助：解包 asset 响应 ---------------------------------------
  // 后端返 {code:0, msg:"", list:[{cash, ...}]}，拦截器解 list → resp.data 为数组
  function _parseAsset(resp) {
    const list = Array.isArray(resp) ? resp : (Array.isArray(resp?.list) ? resp.list : [resp])
    const a = list[0]
    if (!a) return null
    return {
      cash: Number(a.cash) || 0,
      frozen_cash: Number(a.frozen_cash) || 0,
      market_value: Number(a.market_value) || 0,
      total_asset: Number(a.total_asset) || 0
    }
  }

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
        const a = _parseAsset(rAsset.value)
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
        orders.value = rawOrders.map(_recomputeStatus)
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
        const a = _parseAsset(rAsset.value)
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
        orders.value = rawOrders.map(_recomputeStatus)
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
      const a = _parseAsset(await api.getAsset())
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

  // ---- ws 推送入口（ws.js 调） ----------------------------------------

  /** ws._onPositionCfm 调用：合并持仓推送 + 写日志 */
  function applyPositionPush(row) {
    if (!row || !row.stock_code) return
    const idx = positions.value.findIndex((p) => p.stock_code === row.stock_code)
    if (idx >= 0) {
      positions.value[idx] = { ...positions.value[idx], ...row }
    } else if (row.volume) {
      positions.value.unshift(row)
    }
    log('info', '交易', 'ws', `持仓推送: ${row.stock_code} → ${row.vol}@${row.cost_price}`)
  }

  /** ws._onAssetCfm 调用 */
  function applyAssetPush(row) {
    if (!row) return
    cachedAsset.value = {
      cash: Number(row.cash) || 0,
      frozen_cash: Number(row.frozen_cash) || 0,
      market_value: Number(row.market_value) || 0,
      total_asset: Number(row.total_asset) || 0
    }
    log('info', '交易', 'ws', `资产推送: 总资产 ¥${cachedAsset.value.total_asset.toLocaleString()}`)
  }

  /**
   * v8 增: 委托 status 防御性重算 helper
   *   - 入参 row (任意对象,只要含 volume/traded_volume 可选)
   *   - 返回新对象(不可变),status = inferOrderStatus({...row}, null)
   *   - 不传 brokerStatus: 完全按 traded_volume / volume 推断
   *     满足用户需求"按已成数量计算状态"(cancelled_volume 字段后续 PR 引入)
   *   - 缺 volume 或 traded_volume 时原样返回
   *   - 用于: bootstrap / refresh / applyOrderPush 三处入口
   */
  function _recomputeStatus(o) {
    if (o == null) return o
    if (o.volume == null || o.traded_volume == null) return o
    return {
      ...o,
      status: inferOrderStatus(
        {
          status: o.status,
          volume: o.volume,
          traded_volume: o.traded_volume
        },
        null
      )
    }
  }

  /** ws._onOrderCfm 调用：合并委托 + 写日志
   *  v6: 匹配键用 order_no（本地 8 位序号 PK），order_id 可能为 null
   *      收到推送时调前端 inferOrderStatus 防御性重算 status
   *  v8: 守门 = (activeTrdDate, order_no)
   *      - 推送 row.trd_date != activeTrdDate → 忽略（broker 偶尔推老委托的历史变更）
   *      - activeTrdDate == null（降级）→ 放行（log warn）
   *      - 已有订单的 trd_date 也要守门（防止 push 覆盖跨日缓存）
   */
  function applyOrderPush(row, action /* 'open' | 'update' | 'status' */) {
    if (!row || !row.order_no) return
    // v8 激活日守门
    if (activeTrdDate.value && row.trd_date && row.trd_date !== activeTrdDate.value) {
      log('warn', '交易', 'ws', `委托推送忽略: trd_date=${row.trd_date} != active=${activeTrdDate.value} (${row.stock_code} ${row.order_no})`)
      return
    }
    // 防御性重算 status（与后端 _infer_order_status 一致;不传 brokerStatus 完全按 cum/vol 算）
    row.status = _recomputeStatus(row).status
    const idx = orders.value.findIndex((o) => o.order_no === row.order_no)
    if (idx >= 0) {
      orders.value[idx] = { ...orders.value[idx], ...row }
      log('info', '交易', 'ws', `委托状态: ${row.stock_code} ${action} (${row.status || ''})`)
    } else {
      orders.value.unshift(row)
      log('info', '交易', 'ws', `新委托: ${row.stock_code} ${row.order_type === '23' ? '买' : '卖'} ${row.volume}@${row.price}`)
    }
  }

  /** ws._onTradeCfm 调用
   *  v8: 守门 = (activeTrdDate, trade_id) → 推送 row.trd_date != active 忽略
   *      成交按 trade_id 唯一, trd_date 是额外维度
   */
  function applyTradePush(row) {
    if (!row || !row.trade_id) return
    // v8 激活日守门
    if (activeTrdDate.value && row.trd_date && row.trd_date !== activeTrdDate.value) {
      log('warn', '交易', 'ws', `成交推送忽略: trd_date=${row.trd_date} != active=${activeTrdDate.value} (${row.stock_code})`)
      return
    }
    const idx = trades.value.findIndex((t) => t.trade_id === row.trade_id)
    if (idx < 0) {
      // v7 增: 补全 trd_date / order_no / remark
      //   跟后端 TradeOut schema 对齐 (v6 schema-refinement)
      //   前端做 T 敞口/配平需要 order_no 关联委托
      //   trd_date 用于跨日分组; remark 用于关联 Order.remark = 本地 order_no
      trades.value.unshift({
        trade_id: row.trade_id,
        order_id: row.order_id || '',
        order_no: row.order_no || row.remark || '',  // 兼容 broker 透传 remark
        trd_date: row.trd_date || _today_yyyymmdd(),
        stock_code: row.stock_code || '',
        order_type: row.order_type || '',
        volume: Number(row.volume) || 0,
        price: Number(row.price) || 0,
        amount: Number(row.amount) || Number(row.volume || 0) * Number(row.price || 0),
        trade_time: row.trade_time || _now_hms()
      })
      log('ok', '交易', 'ws', `成交通知: ${row.stock_code} ${row.order_type === '23' ? '买' : '卖'} ${row.volume}@${row.price}`)
    }
  }

  /** ws._onQuote 调用：白名单过滤 + 写入 quote store */
  function applyQuote(row) {
    if (!row || !row.stock_code) return false
    if (!positionCodes.value.has(row.stock_code)) return false
    const q = useQuoteStore()
    q.update({
      stock_code: row.stock_code,
      last_price: row.last_price,
      fields: row.fields,
      body: row.body,
      ts: row.ts || Date.now()
    })
    return true
  }

  function _now_hms() {
    const d = new Date()
    return [d.getHours(), d.getMinutes(), d.getSeconds()]
      .map((n) => String(n).padStart(2, '0')).join(':')
  }

  // v7 增: 跟后端 trd_date 格式对齐 (YYYYMMDD)
  function _today_yyyymmdd() {
    const d = new Date()
    return [d.getFullYear(), d.getMonth() + 1, d.getDate()]
      .map((n) => String(n).padStart(2, '0')).join('')
  }

  return {
    // state
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
