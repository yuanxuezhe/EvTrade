/**
 * Trade.test.js — 交易下单 view 单测 (v13 panel 嵌入重构)
 *
 * 验证 2 列 grid + 2 个 panel 挂载 + onApplyPrice 传递
 */
// @vitest-environment jsdom
import { describe, it, expect, vi } from 'vitest'

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
import { mountView } from '../setup-view'
import Trade from '../../src/views/Trade.vue'

// 子组件 stub (避免 OrderForm / QuotePanel 内部依赖)
const StubOrderForm = { template: '<div class="order-form-stub" />', emits: ['update:stockCode'] }
const StubQuotePanel = { template: '<div class="quote-panel-stub" />', emits: ['apply-price'] }
const StubTodayOrdersPanel = { template: '<div class="today-orders-panel-stub" />' }
const StubTodayTradesPanel = { template: '<div class="today-trades-panel-stub" />' }

describe('Trade', () => {
  it('mounts', () => {
    const wrapper = mountView(Trade, {
      stubs: {
        OrderForm: StubOrderForm,
        QuotePanel: StubQuotePanel,
        TodayOrdersPanel: StubTodayOrdersPanel,
        TodayTradesPanel: StubTodayTradesPanel
      }
    })
    expect(wrapper.exists()).toBe(true)
    expect(wrapper.find('.trade-view').exists()).toBe(true)
  })

  it('包含 2 列 grid + 左右两列', () => {
    const wrapper = mountView(Trade, {
      stubs: {
        OrderForm: StubOrderForm,
        QuotePanel: StubQuotePanel,
        TodayOrdersPanel: StubTodayOrdersPanel,
        TodayTradesPanel: StubTodayTradesPanel
      }
    })
    expect(wrapper.find('.trade-grid').exists()).toBe(true)
    expect(wrapper.find('.trade-form-col').exists()).toBe(true)
    expect(wrapper.find('.trade-panels-col').exists()).toBe(true)
  })

  it('左列: OrderForm + QuotePanel', () => {
    const wrapper = mountView(Trade, {
      stubs: {
        OrderForm: StubOrderForm,
        QuotePanel: StubQuotePanel,
        TodayOrdersPanel: StubTodayOrdersPanel,
        TodayTradesPanel: StubTodayTradesPanel
      }
    })
    expect(wrapper.find('.order-form-stub').exists()).toBe(true)
    expect(wrapper.find('.quote-panel-stub').exists()).toBe(true)
  })

  it('右列: TodayOrdersPanel + TodayTradesPanel', () => {
    const wrapper = mountView(Trade, {
      stubs: {
        OrderForm: StubOrderForm,
        QuotePanel: StubQuotePanel,
        TodayOrdersPanel: StubTodayOrdersPanel,
        TodayTradesPanel: StubTodayTradesPanel
      }
    })
    expect(wrapper.find('.today-orders-panel-stub').exists()).toBe(true)
    expect(wrapper.find('.today-trades-panel-stub').exists()).toBe(true)
  })

  it('onApplyPrice → 调 OrderForm.onExternalApply', () => {
    let captured = null
    const StubOrderFormCapture = {
      template: '<div class="order-form-stub" />',
      methods: {
        onExternalApply(price) { captured = price }
      }
    }
    const wrapper = mountView(Trade, {
      stubs: {
        OrderForm: StubOrderFormCapture,
        QuotePanel: StubQuotePanel,
        TodayOrdersPanel: StubTodayOrdersPanel,
        TodayTradesPanel: StubTodayTradesPanel
      }
    })
    // 直接调 view 的 onApplyPrice
    wrapper.vm.onApplyPrice(12.34)
    expect(captured).toBe(12.34)
  })
})