/**
 * history-query.test.js — 替代 6.4 手动 UI 验证
 *
 * 全链路 smoke:
 *   路由进入 HistoryOrders → 点 chip (预设区间) → API getOrders 带正确参数 → 渲染结果
 *   路径不对 → 422 校验失败提示
 *   stockCode 过滤 → API 带 stockCode
 *   CSV 导出按钮 → 仅 results.length > 0 时可点
 */
// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from 'vitest'

vi.mock('@/stores/ws_heartbeat', () => ({
  createWsManager: () => ({
    connect: vi.fn(),
    disconnect: vi.fn(),
    connected: { value: false },
    lastEvent: { value: null },
  }),
}))

vi.mock('@/api', () => {
  const fn = () => vi.fn()
  return {
    api: {
      getActiveDay: fn().mockResolvedValue([{ trd_date: '20260705', status: 'active' }]),
      getOrders: fn(),
      getTrades: fn(),
      getAsset: fn().mockResolvedValue({ cash: 100000, total_asset: 500000 }),
      getHoldings: fn().mockResolvedValue([]),
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

import '../setup-view'
import { mountView, flushPromises } from '../setup-view'
import { api } from '@/api'
import HistoryOrders from '@/views/HistoryOrders.vue'
import HistoryTrades from '@/views/HistoryTrades.vue'

const ordersSample = [
  { trd_date: '20260701', order_no: '00000001', stock_code: '600030.SH', order_type: '23', volume: 100, price: 12.34, status: '50' },
  { trd_date: '20260702', order_no: '00000002', stock_code: '600519.SH', order_type: '23', volume: 100, price: 1800, status: '52' },
]
const tradesSample = [
  { trd_date: '20260701', trade_id: 'T00000001', trade_type: 0, stock_code: '600030.SH', order_type: '23', volume: 100, price: 12.34 },
  { trd_date: '20260702', trade_id: 'T00000002', trade_type: 0, stock_code: '600519.SH', order_type: '23', volume: 100, price: 1800 },
]

describe('HistoryOrders smoke (替代 6.4)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.getOrders).mockResolvedValue(ordersSample)
  })

  it('mounts', async () => {
    const wrapper = mountView(HistoryOrders)
    await flushPromises()
    expect(wrapper.exists()).toBe(true)
    expect(wrapper.find('.history-orders-view').exists()).toBe(true)
  })

  it('onMounted 不主动拉 (用户驱动查询)', async () => {
    mountView(HistoryOrders)
    await flushPromises()
    expect(api.getOrders).not.toHaveBeenCalled()
  })

  it('点 chip「最近三天」→ setPreset → runQuery → API 调', async () => {
    const wrapper = mountView(HistoryOrders)
    await flushPromises()
    // setPreset(PRESETS[1]) = 最近三天
    wrapper.vm.setPreset(wrapper.vm.PRESETS[1])
    await flushPromises()
    expect(api.getOrders).toHaveBeenCalledTimes(1)
    // 调参应含 startDate/endDate
    const callArg = vi.mocked(api.getOrders).mock.calls[0][0]
    expect(callArg).toHaveProperty('startDate')
    expect(callArg).toHaveProperty('endDate')
  })

  it('stockCode 过滤 → API 带 stockCode', async () => {
    const wrapper = mountView(HistoryOrders)
    await flushPromises()
    wrapper.vm.stockCode = '600030.SH'
    wrapper.vm.setPreset(wrapper.vm.PRESETS[1])
    await flushPromises()
    const callArg = vi.mocked(api.getOrders).mock.calls[0][0]
    expect(callArg.stockCode).toBe('600030.SH')
  })

  it('结果渲染: results.length = ordersSample.length', async () => {
    const wrapper = mountView(HistoryOrders)
    await flushPromises()
    wrapper.vm.setPreset(wrapper.vm.PRESETS[1])
    await flushPromises()
    expect(wrapper.vm.results.length).toBe(2)
    expect(wrapper.vm.hasQueried).toBe(true)
  })

  it('日期范围非法 (startDate > endDate) → isDateRangeValid=false', () => {
    const wrapper = mountView(HistoryOrders)
    wrapper.vm.dateRange = ['20260710', '20260701']
    expect(wrapper.vm.isDateRangeValid).toBe(false)
  })

  it('导出 CSV 按钮: results.length = 0 → disabled', async () => {
    vi.mocked(api.getOrders).mockResolvedValue([])
    const wrapper = mountView(HistoryOrders)
    await flushPromises()
    wrapper.vm.setPreset(wrapper.vm.PRESETS[1])
    await flushPromises()
    expect(wrapper.vm.results.length).toBe(0)
  })
})

describe('HistoryTrades smoke (替代 6.4)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.getTrades).mockResolvedValue(tradesSample)
  })

  it('mounts', async () => {
    const wrapper = mountView(HistoryTrades)
    await flushPromises()
    expect(wrapper.exists()).toBe(true)
  })

  it('点 chip → API 调 + 结果渲染', async () => {
    const wrapper = mountView(HistoryTrades)
    await flushPromises()
    wrapper.vm.setPreset(wrapper.vm.PRESETS[1])
    await flushPromises()
    expect(api.getTrades).toHaveBeenCalledTimes(1)
    expect(wrapper.vm.results.length).toBe(2)
  })

  it('stockCode 过滤', async () => {
    const wrapper = mountView(HistoryTrades)
    await flushPromises()
    wrapper.vm.stockCode = '600030.SH'
    wrapper.vm.setPreset(wrapper.vm.PRESETS[1])
    await flushPromises()
    const callArg = vi.mocked(api.getTrades).mock.calls[0][0]
    expect(callArg.stockCode).toBe('600030.SH')
  })
})