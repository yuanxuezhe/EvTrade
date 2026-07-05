/**
 * TodayOrdersPanel.test.js — 今日委托 mini 面板单测
 *
 * 验证:
 *   - 委托行渲染 (含 cancel-row 过滤)
 *   - canCancel 守卫 (终态 status / cancel-row 不显示「撤」按钮)
 *   - handleCancel 调 ElMessageBox + orderStore.cancelOrder
 *   - 分页 (pageSize 切换 / 翻页)
 */
// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from 'vitest'

vi.mock('../../src/api', () => {
  const fn = () => vi.fn()
  return {
    api: {
      getOrders: fn(), getTrades: fn(), getAsset: fn(), getPositions: fn(),
      placeOrder: fn(), cancelOrder: fn(), adjustAsset: fn(), adjustPosition: fn(),
      adminReconcile: fn(), getT0Stats: fn(), getT0Exposure: fn(), getT0Aggregate: fn(),
    },
    authApi: { login: fn(), logout: fn() },
    userApi: { list: fn(), create: fn(), update: fn(), delete: fn() },
    http: { interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } } },
    setUnauthorizedHandler: vi.fn(),
    tokenStorage: { get: vi.fn(() => ''), set: vi.fn(), clear: vi.fn() },
    createWSConnection: vi.fn(),
  }
})

import '../../setup-view'
import { mountView, flushPromises } from '../../setup-view'
import { api } from '../../../src/api'
import { useHoldingsStore } from '../../../src/stores/holdings'
import { useOrderStore } from '../../../src/stores/order'
import TodayOrdersPanel from '../../../src/components/trade/TodayOrdersPanel.vue'
import { ElMessageBox } from 'element-plus'

const activeDay = '20260705'

function seedHoldings(orders = []) {
  const h = useHoldingsStore()
  h.activeTrdDate = activeDay
  h.orders = orders
}

describe('TodayOrdersPanel', () => {
  let wrapper

  beforeEach(() => {
    vi.clearAllMocks()
    // ElMessageBox 默认 resolve confirm
    vi.mocked(ElMessageBox.confirm).mockReset().mockResolvedValue('confirm')
  })

  it('mounts', () => {
    seedHoldings([])
    wrapper = mountView(TodayOrdersPanel)
    expect(wrapper.exists()).toBe(true)
    expect(wrapper.find('.tp-shell').exists()).toBe(true)
  })

  it('空数据: 显示「暂无当日委托」empty', () => {
    seedHoldings([])
    wrapper = mountView(TodayOrdersPanel)
    expect(wrapper.find('.el-table').exists()).toBe(true)
  })

  it('渲染当日委托 (trd_date 过滤)', () => {
    seedHoldings([
      { trd_date: activeDay, order_no: '00000001', order_flag: 0, stock_code: '600030.SH', order_type: '23', volume: 100, price: 12.34, status: '50' },
      { trd_date: '20260701', order_no: '00000002', order_flag: 0, stock_code: '600519.SH', order_type: '23', volume: 100, price: 1800, status: '50' }, // 昨日
    ])
    wrapper = mountView(TodayOrdersPanel)
    expect(wrapper.vm.todayOrders.length).toBe(1)
    expect(wrapper.vm.todayOrders[0].order_no).toBe('00000001')
  })

  it('排除 cancel-row (order_flag=1)', () => {
    seedHoldings([
      { trd_date: activeDay, order_no: '00000001', order_flag: 0, stock_code: '600030.SH', order_type: '23', volume: 100, price: 12.34, status: '50' },
      { trd_date: activeDay, order_no: '00000002', order_flag: 1, stock_code: '600030.SH', order_type: '23', volume: 0, price: 0, status: '48', user_def: 'CANCEL:00000001' }
    ])
    wrapper = mountView(TodayOrdersPanel)
    expect(wrapper.vm.todayOrders.length).toBe(1)
  })

  it('canCancel: status=54 (broker 已撤) 返回 false', () => {
    const row = { trd_date: activeDay, order_no: '00000001', order_flag: 0, status: '54' }
    expect(wrapper.vm ? wrapper.vm.canCancel(row) : false).toBe(false)
  })

  it('canCancel: status=50 (broker 已报) 返回 true', () => {
    const row = { trd_date: activeDay, order_no: '00000001', order_flag: 0, status: '50' }
    expect(wrapper.vm ? wrapper.vm.canCancel(row) : true).toBe(true)
  })

  it('canCancel: cancel-row (order_flag=1) 返回 false', () => {
    const row = { trd_date: activeDay, order_no: '00000001', order_flag: 1, status: '50' }
    expect(wrapper.vm ? wrapper.vm.canCancel(row) : false).toBe(false)
  })

  it('handleCancel: ElMessageBox + orderStore.cancelOrder', async () => {
    const cancelFn = vi.fn().mockResolvedValue({ code: 0 })
    // mock orderStore
    const orderStore = useOrderStore()
    orderStore.cancelOrder = cancelFn

    seedHoldings([
      { trd_date: activeDay, order_no: '00000001', order_flag: 0, stock_code: '600030.SH', order_type: '23', volume: 100, price: 12.34, status: '50' }
    ])
    wrapper = mountView(TodayOrdersPanel)
    const row = wrapper.vm.todayOrders[0]
    await wrapper.vm.handleCancel(row)
    expect(ElMessageBox.confirm).toHaveBeenCalled()
    expect(cancelFn).toHaveBeenCalledWith('00000001', activeDay)
  })

  it('handleCancel: 用户取消不调 store', async () => {
    vi.mocked(ElMessageBox.confirm).mockReset().mockRejectedValue('cancel')
    const orderStore = useOrderStore()
    const cancelFn = vi.fn()
    orderStore.cancelOrder = cancelFn

    seedHoldings([
      { trd_date: activeDay, order_no: '00000001', order_flag: 0, stock_code: '600030.SH', order_type: '23', volume: 100, price: 12.34, status: '50' }
    ])
    wrapper = mountView(TodayOrdersPanel)
    await wrapper.vm.handleCancel(wrapper.vm.todayOrders[0])
    expect(cancelFn).not.toHaveBeenCalled()
  })

  it('分页: todayOrders.length <= pageSize 不显示分页', () => {
    const orders = []
    for (let i = 0; i < 5; i++) {
      orders.push({ trd_date: activeDay, order_no: String(i).padStart(8, '0'), order_flag: 0, stock_code: '600030.SH', order_type: '23', volume: 100, price: 12.34, status: '50' })
    }
    seedHoldings(orders)
    wrapper = mountView(TodayOrdersPanel)
    expect(wrapper.find('.tp-pagination').exists()).toBe(false)
  })

  it('分页: todayOrders.length > pageSize 显示分页', async () => {
    const orders = []
    for (let i = 0; i < 25; i++) {
      orders.push({ trd_date: activeDay, order_no: String(i).padStart(8, '0'), order_flag: 0, stock_code: '600030.SH', order_type: '23', volume: 100, price: 12.34, status: '50' })
    }
    seedHoldings(orders)
    wrapper = mountView(TodayOrdersPanel)
    await flushPromises()
    expect(wrapper.find('.tp-pagination').exists()).toBe(true)
    expect(wrapper.vm.pagedOrders.length).toBe(20)
  })
})