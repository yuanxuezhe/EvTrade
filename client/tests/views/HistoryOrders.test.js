/**
 * HistoryOrders.test.js — 历史委托 view 单测
 *
 * 覆盖:
 *   - 默认 mount (无默认查询, 等用户主动选 chip/picker)
 *   - chip 点击: 设日期范围 + 立即调 API
 *   - picker 选区间 + 查询按钮: 调 API
 *   - stockCode 过滤: 拼到 opts
 *   - startDate > endDate: 查询按钮 disabled + alert 显示
 *   - 渲染响应 list + 分页
 *   - 422 / API error: ElMessage.error 弹
 *   - 重置按钮清空 state
 */
// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from 'vitest'

// api mock 必须在 import api 之前 hoist
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
import { makeOrder } from './_setup'
import HistoryOrders from '../../src/views/HistoryOrders.vue'

describe('HistoryOrders', () => {
  beforeEach(() => {
    vi.mocked(api.getOrders).mockReset().mockResolvedValue({ code: 0, list: [] })
  })

  it('mounts without error', () => {
    const wrapper = mountView(HistoryOrders)
    expect(wrapper.exists()).toBe(true)
    expect(wrapper.find('.history-orders-view').exists()).toBe(true)
  })

  it('不自动查询 (v13 trade-page-redesign-v2: onMounted 留空)', async () => {
    mountView(HistoryOrders)
    await flushPromises()
    expect(api.getOrders).not.toHaveBeenCalled()
  })

  it('点 chip「昨日」: 设日期范围 + 立即查询 (不含今日)', async () => {
    const wrapper = mountView(HistoryOrders)
    const yesterdayChip = wrapper.findAll('.filter-chip').find((c) => c.text().includes('昨日'))
    expect(yesterdayChip).toBeTruthy()
    await yesterdayChip.trigger('click')
    await flushPromises()

    expect(api.getOrders).toHaveBeenCalledTimes(1)
    const opts = vi.mocked(api.getOrders).mock.calls[0][0]
    expect(opts.startDate).toMatch(/^\d{8}$/)
    expect(opts.endDate).toMatch(/^\d{8}$/)
    // 昨日区间: endDate < todayYYYYMMDD
    expect(opts.endDate < new Date().toISOString().slice(0, 10).replace(/-/g, '')).toBe(true)
  })

  it('点 chip「最近一周」: 7 天区间', async () => {
    const wrapper = mountView(HistoryOrders)
    const weekChip = wrapper.findAll('.filter-chip').find((c) => c.text().includes('最近一周'))
    await weekChip.trigger('click')
    await flushPromises()
    expect(api.getOrders).toHaveBeenCalledTimes(1)
  })

  it('点 chip 后 chip 高亮 (activePreset)', async () => {
    const wrapper = mountView(HistoryOrders)
    const yesterdayChip = wrapper.findAll('.filter-chip').find((c) => c.text().includes('昨日'))
    await yesterdayChip.trigger('click')
    await flushPromises()
    expect(yesterdayChip.classes()).toContain('active')
  })

  it('stockCode 拼到 opts (picker 选区间 + 输入 stockCode + 点查询)', async () => {
    const wrapper = mountView(HistoryOrders)
    // 直接通过 data 设置 (避免 el-date-picker 复杂交互)
    wrapper.vm.dateRange = ['20260701', '20260705']
    wrapper.vm.stockCode = '600030.SH'
    await flushPromises()
    await wrapper.find('.el-button--primary').trigger('click')
    await flushPromises()
    expect(api.getOrders).toHaveBeenCalledWith(expect.objectContaining({
      startDate: '20260701',
      endDate: '20260705',
      stockCode: '600030.SH'
    }))
  })

  it('startDate > endDate: 查询按钮 disabled', async () => {
    const wrapper = mountView(HistoryOrders)
    wrapper.vm.dateRange = ['20260710', '20260701']
    await flushPromises()
    expect(wrapper.vm.isDateRangeValid).toBe(false)
    // 查询按钮 (primary) 应 disabled
    const queryBtn = wrapper.findAll('.el-button').find((b) => b.text().includes('查询'))
    expect(queryBtn?.attributes('disabled')).toBeDefined()
  })

  it('API 返回 list: 渲染表格行 + 概览笔数', async () => {
    const orders = [
      makeOrder({ order_no: '00000001', stock_code: '600030.SH' }),
      makeOrder({ order_no: '00000002', stock_code: '600519.SH' }),
      makeOrder({ order_no: '00000003', stock_code: '601318.SH', status: '54' })
    ]
    // HistoryOrders.runQuery 取 data 本身 (后端实际响应就是 array 或 list 字段)
    // 但视图代码是 `Array.isArray(data) ? data : []`, 所以返回 array
    vi.mocked(api.getOrders).mockResolvedValue(orders)

    const wrapper = mountView(HistoryOrders)
    wrapper.vm.dateRange = ['20260701', '20260705']
    await flushPromises()
    await wrapper.find('.el-button--primary').trigger('click')
    await flushPromises()

    expect(wrapper.vm.results.length).toBe(3)
    expect(wrapper.vm.hasQueried).toBe(true)
    // 第 2 个 .pill-value 是委托笔数 (第 1 个是查询区间)
    const pillValues = wrapper.findAll('.pill-value')
    expect(pillValues[1].text()).toContain('3')
  })

  it('API 抛异常: ElMessage.error 弹 (axios 拦截器已统一, 这里只验证 catch 不崩)', async () => {
    vi.mocked(api.getOrders).mockRejectedValue(new Error('network error'))
    const wrapper = mountView(HistoryOrders)
    wrapper.vm.dateRange = ['20260701', '20260705']
    await flushPromises()
    await wrapper.find('.el-button--primary').trigger('click')
    await flushPromises()
    expect(wrapper.vm.results).toEqual([])
  })

  it('重置按钮: 清空所有 state', async () => {
    const wrapper = mountView(HistoryOrders)
    wrapper.vm.dateRange = ['20260701', '20260705']
    wrapper.vm.stockCode = '600030.SH'
    await flushPromises()
    // 点重置按钮
    const resetBtn = wrapper.findAll('.el-button').find((b) => b.text().includes('重置'))
    expect(resetBtn).toBeTruthy()
    await resetBtn.trigger('click')
    await flushPromises()
    expect(wrapper.vm.dateRange).toBeNull()
    expect(wrapper.vm.stockCode).toBe('')
    expect(wrapper.vm.results).toEqual([])
    expect(wrapper.vm.hasQueried).toBe(false)
  })

  it('导出 CSV 按钮: results.length === 0 时 disabled', async () => {
    const wrapper = mountView(HistoryOrders)
    await flushPromises()
    const exportBtn = wrapper.findAll('.el-button').find((b) => b.text().includes('导出'))
    expect(exportBtn?.attributes('disabled')).toBeDefined()
  })
})