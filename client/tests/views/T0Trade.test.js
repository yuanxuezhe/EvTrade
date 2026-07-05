/**
 * T0Trade.test.js — 快速做T view 单测
 *
 * 验证:
 *   - 主表渲染 (持仓行 + 操作列 4 按钮)
 *   - sort-change 写入 sortBy/sortOrder → sortedRows 重排
 *   - buyState/sellState disabled 守卫 (vol=0 → buy disabled)
 *   - pct / priceType 设置条双向联动
 *   - 净敞口 / 配平按钮文本 (净额=0 → '配平', ≠0 → '配±N')
 */
// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from 'vitest'

vi.mock('../../src/api', () => {
  const fn = () => vi.fn()
  return {
    api: {
      getOrders: fn(), getTrades: fn(), getAsset: fn(), getHoldings: fn(),
      getPositions: fn(), getActiveDay: fn(),
      placeOrder: fn().mockResolvedValue({ code: 0, list: [{}] }),
      cancelOrder: fn(), adjustAsset: fn(), adjustPosition: fn(),
      adminReconcile: fn(),
      getT0Stats: fn(), getT0Exposure: fn(), getT0Aggregate: fn(),
    },
    authApi: { login: fn(), logout: fn() },
    userApi: { list: fn(), create: fn(), update: fn(), delete: fn() },
    http: { interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } } },
    setUnauthorizedHandler: vi.fn(),
    tokenStorage: { get: vi.fn(() => ''), set: vi.fn(), clear: vi.fn() },
    createWSConnection: vi.fn(),
  }
})

// mock t0_stats API
vi.mock('../../src/api/t0_stats', () => ({
  t0StatsApi: {
    get: vi.fn().mockResolvedValue(null),
    getHistory: vi.fn().mockResolvedValue({ points: [] }),
    getAggregate: vi.fn().mockResolvedValue({ summary: {}, by_stock: [] }),
  },
}))

import '../setup-view'
import { mountView, flushPromises } from '../setup-view'
import { useHoldingsStore } from '../../src/stores/holdings'
import T0Trade from '../../src/views/T0Trade.vue'

const positions = [
  { stock_code: '600030.SH', stock_name: '中信证券', vol: 1000, avl_vol: 1000, cost_price: 12.0, last_price: 13.0 },
  { stock_code: '600519.SH', stock_name: '贵州茅台', vol: 0,    avl_vol: 0,    cost_price: 1800, last_price: 1750 },
  { stock_code: '000001.SZ', stock_name: '平安银行', vol: 500,  avl_vol: 500,  cost_price: 10.0, last_price: 11.5 },
]

function seedHoldings(p = positions) {
  const h = useHoldingsStore()
  h.positions = p
  h.cachedAsset = { cash: 100000, frozen_cash: 0, market_value: 50000, total_asset: 150000 }
}

describe('T0Trade', () => {
  beforeEach(() => {
    seedHoldings()
  })

  it('mounts', async () => {
    const wrapper = mountView(T0Trade)
    await flushPromises()
    expect(wrapper.exists()).toBe(true)
    expect(wrapper.find('.t0-trade').exists()).toBe(true)
  })

  it('渲染主表 + 行数 = positions.length', async () => {
    const wrapper = mountView(T0Trade)
    await flushPromises()
    expect(wrapper.vm.sortedRows.length).toBe(3)
  })

  it('onSortChange 写入 sortBy / sortOrder', async () => {
    const wrapper = mountView(T0Trade)
    await flushPromises()
    wrapper.vm.onSortChange({ prop: 'vol', order: 'ascending' })
    expect(wrapper.vm.sortBy).toBe('vol')
    expect(wrapper.vm.sortOrder).toBe('ascending')
    // 升序: 0 < 500 < 1000
    expect(wrapper.vm.sortedRows[0].stock_code).toBe('600519.SH')
    expect(wrapper.vm.sortedRows[2].stock_code).toBe('600030.SH')
  })

  it('sortOrder = descending: 倒序', async () => {
    const wrapper = mountView(T0Trade)
    await flushPromises()
    wrapper.vm.onSortChange({ prop: 'vol', order: 'descending' })
    expect(wrapper.vm.sortedRows[0].stock_code).toBe('600030.SH')
    expect(wrapper.vm.sortedRows[2].stock_code).toBe('600519.SH')
  })

  it('sortOrder=null → 保持原顺序', async () => {
    const wrapper = mountView(T0Trade)
    await flushPromises()
    wrapper.vm.onSortChange({ prop: 'vol', order: 'ascending' })
    wrapper.vm.onSortChange({ prop: 'vol', order: null })
    expect(wrapper.vm.sortBy).toBe(null)
    expect(wrapper.vm.sortedRows[0].stock_code).toBe('600030.SH')
  })

  it('buyState: vol=0 → disabled=true (持仓为 0 不能按比例买)', () => {
    const wrapper = mountView(T0Trade)
    const empty = positions[1]  // 600519.SH vol=0
    const state = wrapper.vm.buyState(empty)
    expect(state.disabled).toBe(true)
  })

  it('buyState: vol>0 → disabled=false', () => {
    const wrapper = mountView(T0Trade)
    const ok = positions[0]  // 600030.SH vol=1000
    const state = wrapper.vm.buyState(ok)
    expect(state.disabled).toBe(false)
  })

  it('netExposure: 缺 t0Stats → 0', () => {
    const wrapper = mountView(T0Trade)
    expect(wrapper.vm.netExposure(positions[0])).toBe(0)
  })

  it('netExposure: 有 t0Stats → buy - sell', () => {
    const wrapper = mountView(T0Trade)
    wrapper.vm.t0StatsMap = { '600030.SH': { today_buy_volume: 800, today_sell_volume: 300 } }
    expect(wrapper.vm.netExposure(positions[0])).toBe(500)
  })

  it('getBalanceLabel: 净额=0 → "配平"', () => {
    const wrapper = mountView(T0Trade)
    expect(wrapper.vm.getBalanceLabel(positions[0])).toBe('配平')
  })

  it('getBalanceLabel: 净额>0 → "配-N" (卖平)', () => {
    const wrapper = mountView(T0Trade)
    wrapper.vm.t0StatsMap = { '600030.SH': { today_buy_volume: 500, today_sell_volume: 0 } }
    expect(wrapper.vm.getBalanceLabel(positions[0])).toBe('配-500')
  })

  it('getBalanceLabel: 净额<0 → "配+N" (买平)', () => {
    const wrapper = mountView(T0Trade)
    wrapper.vm.t0StatsMap = { '600030.SH': { today_buy_volume: 0, today_sell_volume: 500 } }
    expect(wrapper.vm.getBalanceLabel(positions[0])).toBe('配+500')
  })

  it('quickPct 默认值', () => {
    const wrapper = mountView(T0Trade)
    expect([25, 50, 75, 100]).toContain(wrapper.vm.quickPct)
  })

  it('PCT_OPTIONS 包含 25/50/75/100', () => {
    const wrapper = mountView(T0Trade)
    expect(wrapper.vm.PCT_OPTIONS).toEqual([25, 50, 75, 100])
  })

  it('_moveSelection: 选下一行', () => {
    const wrapper = mountView(T0Trade)
    wrapper.vm.selectedRowCode = '600030.SH'
    wrapper.vm._moveSelection(1)
    expect(wrapper.vm.selectedRowCode).toBe('600519.SH')
    wrapper.vm._moveSelection(-1)
    expect(wrapper.vm.selectedRowCode).toBe('600030.SH')
  })

  it('_moveSelection: 越界 clamp', () => {
    const wrapper = mountView(T0Trade)
    wrapper.vm.selectedRowCode = '000001.SZ'
    wrapper.vm._moveSelection(1)  // 越界
    expect(wrapper.vm.selectedRowCode).toBe('000001.SZ')
    wrapper.vm.selectedRowCode = '600030.SH'
    wrapper.vm._moveSelection(-1)  // 越界
    expect(wrapper.vm.selectedRowCode).toBe('600030.SH')
  })

  it('cumHistory: historyData 缺 → 空数组', () => {
    const wrapper = mountView(T0Trade)
    expect(wrapper.vm.cumHistory.length).toBe(0)
  })

  it('cumHistory: 累加 realized_pnl', () => {
    const wrapper = mountView(T0Trade)
    wrapper.vm.historyData = { points: [{ realized_pnl: 100 }, { realized_pnl: -50 }, { realized_pnl: 200 }] }
    expect(wrapper.vm.cumHistory.length).toBe(3)
    expect(wrapper.vm.cumHistory[2].cum_pnl).toBe(250)
  })

  it('ptRowClass: 选中行 is-selected', () => {
    const wrapper = mountView(T0Trade)
    wrapper.vm.stockCode = '600030.SH'
    expect(wrapper.vm.ptRowClass({ row: positions[0] })).toContain('is-selected')
    expect(wrapper.vm.ptRowClass({ row: positions[1] })).not.toContain('is-selected')
  })

  // ─── change-quota-frame: quota frame + 行内配额列 ───

  it('quota frame 5 pill 渲染', async () => {
    const wrapper = mountView(T0Trade)
    await flushPromises()
    const pills = wrapper.findAll('.qf-pill')
    expect(pills.length).toBe(5)
    expect(pills[0].attributes('data-pill')).toBe('cashAvail')
    expect(pills[1].attributes('data-pill')).toBe('frozenCash')
    expect(pills[2].attributes('data-pill')).toBe('t0AvailVol')
    expect(pills[3].attributes('data-pill')).toBe('todayPnl')
    expect(pills[4].attributes('data-pill')).toBe('marketValue')
  })

  it('quotaAggregate.cashAvail = cash - frozen_cash', () => {
    const wrapper = mountView(T0Trade)
    expect(wrapper.vm.quotaAggregate.cashAvail).toBe(100000)  // 100000 - 0
  })

  it('quotaAggregate.t0AvailVol = sum(avl_vol)', () => {
    const wrapper = mountView(T0Trade)
    expect(wrapper.vm.quotaAggregate.t0AvailVol).toBe(1500)  // 1000 + 500 + 0
  })

  it('todayPnlText: 正 → "+¥X"', () => {
    const wrapper = mountView(T0Trade)
    wrapper.vm.t0StatsMap = { '600030.SH': { realized_pnl: 800 }, '600519.SH': { realized_pnl: -300 } }
    expect(wrapper.vm.todayPnlText).toMatch(/^\+¥/)
    expect(wrapper.vm.todayPnlClass).toBe('qf-pill--up')
  })

  it('todayPnlText: 负 → "-¥X"', () => {
    const wrapper = mountView(T0Trade)
    wrapper.vm.t0StatsMap = { '600030.SH': { realized_pnl: -100 } }
    expect(wrapper.vm.todayPnlText).toMatch(/^-¥/)
    expect(wrapper.vm.todayPnlClass).toBe('qf-pill--down')
  })

  it('quotaForRow: 可买按 cash + last_price 估算', () => {
    const wrapper = mountView(T0Trade)
    const row = { stock_code: '600030.SH', avl_vol: 1000 }
    const q = wrapper.vm.quotaForRow(row)
    // cash=100000, 默认 last_price 未设 → mock quoteStore.getLastPrice 返 null → maxBuyable=0
    expect(q.maxBuyable).toBe(0)
    expect(q.maxSellable).toBe(1000)  // row.avl_vol = 1000
  })

  it('quotaForRow: 可卖 = avl_vol', () => {
    const wrapper = mountView(T0Trade)
    const row = { stock_code: '600030.SH', avl_vol: 500 }
    const q = wrapper.vm.quotaForRow(row)
    expect(q.maxSellable).toBe(500)
  })

  it('quotaLevel: 颜色阈值 (1000/100/1/0)', () => {
    const wrapper = mountView(T0Trade)
    expect(wrapper.vm.quotaLevel(5000)).toBe('high')
    expect(wrapper.vm.quotaLevel(500)).toBe('mid')
    expect(wrapper.vm.quotaLevel(50)).toBe('low')
    expect(wrapper.vm.quotaLevel(0)).toBe('none')
  })
})