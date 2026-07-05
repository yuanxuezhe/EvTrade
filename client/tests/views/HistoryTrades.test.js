/**
 * HistoryTrades.test.js — 历史成交 view 单测
 *
 * 与 HistoryOrders 对称, 覆盖查询 / 422 / 重置 / 渲染
 */
// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from 'vitest'

vi.mock('../../src/api', () => {
  const fn = () => vi.fn()
  return {
    api: {
      getOrders: fn(),
      getTrades: fn(),
      getAsset: fn(),
      getPositions: fn(),
      placeOrder: fn(),
      cancelOrder: fn(),
      adjustAsset: fn(),
      adjustPosition: fn(),
      adminReconcile: fn(),
      getT0Stats: fn(),
      getT0Exposure: fn(),
      getT0Aggregate: fn(),
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
import { api } from '../../src/api'
import { makeTrade } from './_setup'
import HistoryTrades from '../../src/views/HistoryTrades.vue'

describe('HistoryTrades', () => {
  beforeEach(() => {
    vi.mocked(api.getTrades).mockReset().mockResolvedValue([])
  })

  it('mounts', () => {
    const wrapper = mountView(HistoryTrades)
    expect(wrapper.exists()).toBe(true)
  })

  it('不自动查询', async () => {
    mountView(HistoryTrades)
    await flushPromises()
    expect(api.getTrades).not.toHaveBeenCalled()
  })

  it('点 chip: 立即查询 (不含今日)', async () => {
    const wrapper = mountView(HistoryTrades)
    const yesterdayChip = wrapper.findAll('.filter-chip').find((c) => c.text().includes('昨日'))
    expect(yesterdayChip).toBeTruthy()
    await yesterdayChip.trigger('click')
    await flushPromises()
    expect(api.getTrades).toHaveBeenCalledTimes(1)
    const opts = vi.mocked(api.getTrades).mock.calls[0][0]
    expect(opts.startDate).toMatch(/^\d{8}$/)
    expect(opts.endDate).toMatch(/^\d{8}$/)
  })

  it('stockCode 拼到 opts', async () => {
    const wrapper = mountView(HistoryTrades)
    wrapper.vm.dateRange = ['20260701', '20260705']
    wrapper.vm.stockCode = '600519.SH'
    await flushPromises()
    await wrapper.find('.el-button--primary').trigger('click')
    await flushPromises()
    expect(api.getTrades).toHaveBeenCalledWith(expect.objectContaining({
      stockCode: '600519.SH'
    }))
  })

  it('startDate > endDate: 查询按钮 disabled', async () => {
    const wrapper = mountView(HistoryTrades)
    wrapper.vm.dateRange = ['20260710', '20260701']
    await flushPromises()
    expect(wrapper.vm.isDateRangeValid).toBe(false)
    const queryBtn = wrapper.findAll('.el-button').find((b) => b.text().includes('查询'))
    expect(queryBtn?.attributes('disabled')).toBeDefined()
  })

  it('API 返回 list: results 更新 + hasQueried', async () => {
    const trades = [
      makeTrade({ trade_id: 'T00000001' }),
      makeTrade({ trade_id: 'T00000002', stock_code: '600519.SH' })
    ]
    vi.mocked(api.getTrades).mockResolvedValue(trades)

    const wrapper = mountView(HistoryTrades)
    wrapper.vm.dateRange = ['20260701', '20260705']
    await flushPromises()
    await wrapper.find('.el-button--primary').trigger('click')
    await flushPromises()
    expect(wrapper.vm.results.length).toBe(2)
    expect(wrapper.vm.hasQueried).toBe(true)
  })

  it('API 异常: results 空数组不崩', async () => {
    vi.mocked(api.getTrades).mockRejectedValue(new Error('network'))
    const wrapper = mountView(HistoryTrades)
    wrapper.vm.dateRange = ['20260701', '20260705']
    await flushPromises()
    await wrapper.find('.el-button--primary').trigger('click')
    await flushPromises()
    expect(wrapper.vm.results).toEqual([])
  })

  it('重置按钮: 清空 state', async () => {
    const wrapper = mountView(HistoryTrades)
    wrapper.vm.dateRange = ['20260701', '20260705']
    wrapper.vm.stockCode = '600030.SH'
    await flushPromises()
    const resetBtn = wrapper.findAll('.el-button').find((b) => b.text().includes('重置'))
    await resetBtn.trigger('click')
    await flushPromises()
    expect(wrapper.vm.dateRange).toBeNull()
    expect(wrapper.vm.stockCode).toBe('')
    expect(wrapper.vm.results).toEqual([])
    expect(wrapper.vm.hasQueried).toBe(false)
  })
})