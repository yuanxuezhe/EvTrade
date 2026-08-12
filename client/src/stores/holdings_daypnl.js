/**
 * holdings_daypnl.js — 当日盈亏 recompute 工厂 (v114.2: store 驱动, 无轮询)
 *
 * Why:
 *   - 当日盈亏权威在 holdings store: 行情推送驱动逐笔重算, 写入 positions[].day_pnl
 *   - 持仓面板读行字段 day_pnl; 仪表盘"今日盈亏" = Σ positions.day_pnl
 *   - 不轮询: 重算靠 quote.tick (行情每来一笔自增), 成交额/费用 map 靠事件驱动重拉
 *     (activeTrdDate 切换 / trades.length 成交推送防抖)
 *
 * 触发矩阵:
 *   - quote.tick        → recomputeAll() 写 p.day_pnl   (行情推送, 每笔重算一次)
 *   - positions 引用变化 → recomputeAll()                (bootstrap 加载/换日, 不等行情)
 *   - activeTrdDate 变化 → refreshDayPnl()               (跨日清旧成交)
 *   - trades.length 变化 → refreshDayPnl(true) 3s 防抖    (今日新成交尽快反映)
 *
 * 调用者: holdings.js 内部 createDayPnlRecompute({ positions, activeTrdDate, trades })
 *   → { start, stop, recomputeAll, refreshDayPnl }; start/stop 挂 _startWatchers/_stopWatchers
 */
import { watch } from 'vue'
import { useT0DayPnl } from '../composables/useT0DayPnl'
import { useQuoteStore } from './quote'

const TRADES_DEBOUNCE_MS = 3000

/**
 * 创建当日盈亏 recompute 控制
 * @param {Ref<Array>} positions      持仓列表 ref (写入 .day_pnl)
 * @param {Ref<string|null>} activeTrdDate 激活交易日 ref
 * @param {Ref<Array>} trades         今日成交 ref
 */
export function createDayPnlRecompute({ positions, activeTrdDate, trades }) {
  let _unwatchTick = null
  let _unwatchPos = null
  let _unwatchDate = null
  let _unwatchTrades = null
  let _debounce = null

  /** 遍历 positions 重算当日盈亏并写回行字段 (无行情/无昨收 → null) */
  function recomputeAll() {
    for (const p of positions.value || []) {
      p.day_pnl = useT0DayPnl.getDayPnl(p)
    }
  }

  /** 拉取成交额/费用 map (同日幂等; force 用于成交推送后强制重拉), 拉完立即算一版 */
  async function refreshDayPnl(force = false) {
    await useT0DayPnl.refresh(activeTrdDate.value || '', force)
    recomputeAll()
  }

  function _onTradesChange() {
    if (_debounce) clearTimeout(_debounce)
    _debounce = setTimeout(() => refreshDayPnl(true), TRADES_DEBOUNCE_MS)
  }

  function start() {
    if (_unwatchTick) return
    // 行情推送驱动: tick 自增 → 逐笔重算写入 positions[].day_pnl
    _unwatchTick = watch(() => useQuoteStore().tick, recomputeAll, { flush: 'post' })
    // positions 引用变化 (bootstrap 加载 / 换日重置) → 立即算一版, 不等行情
    _unwatchPos = watch(() => positions.value, recomputeAll, { flush: 'post' })
    // 交易日切换 → 重拉成交 map (跨日清空旧成交)
    _unwatchDate = watch(() => activeTrdDate.value, () => refreshDayPnl())
    // 今日新增成交 (ws 推送) → 防抖重拉成交 map
    _unwatchTrades = watch(() => trades.value.length, _onTradesChange)
    // 初值: positions 已有数据则立即算一版 + 拉成交 map
    recomputeAll()
    refreshDayPnl()
  }

  function stop() {
    if (_unwatchTick) { _unwatchTick(); _unwatchTick = null }
    if (_unwatchPos) { _unwatchPos(); _unwatchPos = null }
    if (_unwatchDate) { _unwatchDate(); _unwatchDate = null }
    if (_unwatchTrades) { _unwatchTrades(); _unwatchTrades = null }
    if (_debounce) { clearTimeout(_debounce); _debounce = null }
  }

  return { start, stop, recomputeAll, refreshDayPnl }
}
