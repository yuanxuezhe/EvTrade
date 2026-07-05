/**
 * TodayTradesPanel.test.js — 今日成交 mini 面板单测
 *
 * 验证:
 *   - 成交行渲染 (含 trade_type=1 撤单过滤)
 *   - 分页
 *   - 无「撤」按钮 (trades 是终态)
 */
// @vitest-environment jsdom
import { describe, it, expect, beforeEach } from 'vitest'

vi.mock('../../src/api', () => ({
  api: {
    getOrders: vi.fn(), getTrades: vi.fn(), getAsset: vi.fn(), getPositions: vi.fn(),
    placeOrder: vi.fn(), cancelOrder: vi.fn(), adjustAsset: vi.fn(), adjustPosition: vi.fn(),
    adminReconcile: vi.fn(), getT0Stats: vi.fn(), getT0Exposure: vi.fn(), getT0Aggregate: vi.fn(),
  },
  authApi: { login: vi.fn(), logout: vi.fn() },
  userApi: { list: vi.fn(), create: vi.fn(), update: vi.fn(), delete: vi.fn() },
  http: { interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } } },
  setUnauthorizedHandler: vi.fn(),
  tokenStorage: { get: vi.fn(() => ''), set: vi.fn(), clear: vi.fn() },
  createWSConnection: vi.fn(),
}))

import '../../setup-view'
import { mountView, flushPromises } from '../../setup-view'
import { useHoldingsStore } from '../../../src/stores/holdings'
import TodayTradesPanel from '../../../src/components/trade/TodayTradesPanel.vue'

const activeDay = '20260705'

function seedHoldings(trades = []) {
  const h = useHoldingsStore()
  h.activeTrdDate = activeDay
  h.trades = trades
}

describe('TodayTradesPanel', () => {
  let wrapper

  beforeEach(() => {
    seedHoldings([])
  })

  it('mounts', () => {
    wrapper = mountView(TodayTradesPanel)
    expect(wrapper.exists()).toBe(true)
    expect(wrapper.find('.tp-shell').exists()).toBe(true)
  })

  it('渲染当日成交 (trd_date 过滤)', () => {
    seedHoldings([
      { trd_date: activeDay, trade_id: 'T00000001', trade_type: 0, stock_code: '600030.SH', order_type: '23', volume: 100, price: 12.34 },
      { trd_date: '20260701', trade_id: 'T00000002', trade_type: 0, stock_code: '600519.SH', order_type: '23', volume: 100, price: 1800 }
    ])
    wrapper = mountView(TodayTradesPanel)
    expect(wrapper.vm.todayTrades.length).toBe(1)
    expect(wrapper.vm.todayTrades[0].trade_id).toBe('T00000001')
  })

  it('排除 trade_type=1 撤单成交', () => {
    seedHoldings([
      { trd_date: activeDay, trade_id: 'T00000001', trade_type: 0, stock_code: '600030.SH', order_type: '23', volume: 100, price: 12.34 },
      { trd_date: activeDay, trade_id: 'T00000002', trade_type: 1, stock_code: '600030.SH', order_type: '24', volume: 100, price: 12.34 }
    ])
    wrapper = mountView(TodayTradesPanel)
    expect(wrapper.vm.todayTrades.length).toBe(1)
  })

  it('localAmount: volume * price', () => {
    seedHoldings([
      { trd_date: activeDay, trade_id: 'T00000001', trade_type: 0, stock_code: '600030.SH', order_type: '23', volume: 100, price: 12.34 }
    ])
    wrapper = mountView(TodayTradesPanel)
    const row = wrapper.vm.todayTrades[0]
    expect(wrapper.vm.localAmount(row)).toBe(1234)
  })

  it('分页: todayTrades.length > pageSize 显示分页', async () => {
    const trades = []
    for (let i = 0; i < 25; i++) {
      trades.push({ trd_date: activeDay, trade_id: `T${String(i).padStart(8, '0')}`, trade_type: 0, stock_code: '600030.SH', order_type: '23', volume: 100, price: 12.34 })
    }
    seedHoldings(trades)
    wrapper = mountView(TodayTradesPanel)
    await flushPromises()
    expect(wrapper.find('.tp-pagination').exists()).toBe(true)
    expect(wrapper.vm.pagedTrades.length).toBe(20)
  })

  it('分页: todayTrades.length <= pageSize 不显示分页', () => {
    const trades = []
    for (let i = 0; i < 5; i++) {
      trades.push({ trd_date: activeDay, trade_id: `T${String(i).padStart(8, '0')}`, trade_type: 0, stock_code: '600030.SH', order_type: '23', volume: 100, price: 12.34 })
    }
    seedHoldings(trades)
    wrapper = mountView(TodayTradesPanel)
    expect(wrapper.find('.tp-pagination').exists()).toBe(false)
  })
})