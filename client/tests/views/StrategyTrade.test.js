/**
 * StrategyTrade.test.js — 策略交易主视图单测（task 12.5, 12 用例）
 *
 * 覆盖：
 * - mountView 渲染：tabs / 新建按钮 / 左右双 pane
 * - loadStrategies + loadFlagDefinitions 在 mount 时触发
 * - 选中 strategy → 渲染 StrategyMonitor
 * - 新建策略：drafting=true → 显示 StrategyConfig + 提交按钮
 * - 提交 → strategyApi.create 被调
 * - 保存 → strategyApi.update 被调
 * - 删除 → strategyApi.delete 被调
 * - WS payload type='strategy_update' → store.appendAudit 被调
 * - WS payload 缺 strategy_id → 静默丢弃
 * - tab 切换 → list 过滤
 */
// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('../../src/api', () => ({
  api: {},
  authApi: {},
  userApi: {},
  http: { interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } } },
  setUnauthorizedHandler: vi.fn(),
  tokenStorage: { get: vi.fn(), set: vi.fn(), clear: vi.fn() },
  createWSConnection: vi.fn(),
}))
vi.mock('../../src/api/strategy', () => ({
  strategyApi: {
    list: vi.fn().mockResolvedValue([]),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
    getFlagDefinitions: vi.fn().mockResolvedValue({ list: [] }),
    control: vi.fn(),
    getAudit: vi.fn().mockResolvedValue([]),
  },
}))

import '../setup-view'
import { mountView, flushPromises } from '../setup-view'
import { useStrategyStore } from '../../src/stores/strategy'
import StrategyTrade from '../../src/views/StrategyTrade.vue'
import { dispatchPayload } from '../../src/stores/ws_dispatch'
import { strategyApi } from '../../src/api/strategy'

function _seed(strategies = []) {
  const store = useStrategyStore()
  store.strategies = strategies
  return store
}

/** mount + 在 onMounted 触发前阻止覆盖 seed；mock loadStrategies 返 seed 数据 */
async function _mountWithSeed(strategies = []) {
  const store = _seed(strategies)
  strategyApi.list.mockResolvedValue(strategies)
  const wrapper = mountView(StrategyTrade)
  await flushPromises()
  // onMounted 后 store.strategies 已被 mock 重置为 strategies
  expect(store.strategies).toEqual(strategies)
  return { wrapper, store }
}

describe('StrategyTrade', () => {
  beforeEach(() => {
    // 注意: setup-view.js 的 beforeEach 已经 setActivePinia(createPinia()),
    //       这里不能再次创建 (会与 mountView 的 _activePinia plugin 冲突,
    //       导致 view / dispatch 看到的 store 与本测试拿到的 store 不是同一实例)
    vi.clearAllMocks()
    strategyApi.list.mockResolvedValue([])
    strategyApi.create.mockResolvedValue({ id: 99, stock_code: '600000.SH', type: 'general', regimes: [] })
    strategyApi.update.mockResolvedValue({ id: 1, stock_code: '600519.SH', type: 'general', regimes: [] })
    strategyApi.delete.mockResolvedValue(undefined)
  })

  it('renders tabs + 新建按钮 on mount', async () => {
    const wrapper = mountView(StrategyTrade)
    await flushPromises()

    expect(wrapper.find('[data-el="strategy-trade-view"]').exists()).toBe(true)
    expect(wrapper.find('[data-el="strategy-trade-tab"]').exists()).toBe(true)
    expect(wrapper.find('[data-el="strategy-trade-create"]').exists()).toBe(true)
    expect(wrapper.find('[data-el="tab-general"]').exists()).toBe(true)
    expect(wrapper.find('[data-el="tab-t0"]').exists()).toBe(true)
  })

  it('calls loadStrategies + loadFlagDefinitions on mount', async () => {
    mountView(StrategyTrade)
    await flushPromises()
    expect(strategyApi.list).toHaveBeenCalled()
    expect(strategyApi.getFlagDefinitions).toHaveBeenCalled()
  })

  it('shows empty state when no strategies', async () => {
    strategyApi.list.mockResolvedValue([])
    const wrapper = mountView(StrategyTrade)
    await flushPromises()
    // el-empty stub 不渲染 description 文本，断言 el-empty 存在
    expect(wrapper.findAll('.el-empty').length).toBeGreaterThan(0)
  })

  it('create button click → drafting=true + 渲染 StrategyConfig + submit 按钮', async () => {
    const { wrapper } = await _mountWithSeed([])
    await wrapper.find('[data-el="strategy-trade-create"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-el="strategy-trade-submit"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('新建策略（draft）')
  })

  it('cancel draft → 回到空态', async () => {
    const { wrapper } = await _mountWithSeed([])
    await wrapper.find('[data-el="strategy-trade-create"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-el="strategy-trade-submit"]').exists()).toBe(true)

    // 找 el-button stub（data-el='ElButton'）文本含 "取消"
    const buttons = wrapper.findAll('[data-el="ElButton"]')
    const cancelBtn = buttons.find(b => b.text().includes('取消'))
    expect(cancelBtn).toBeDefined()
    await cancelBtn.trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-el="strategy-trade-submit"]').exists()).toBe(false)
  })

  it('select strategy → 渲染 monitor + delete + save 按钮', async () => {
    const strat = { id: 1, stock_code: '600519.SH', type: 'general', status: 'active', reference_price: 10, base_volume: 100, note: 'n', regimes: [] }
    const { wrapper } = await _mountWithSeed([strat])

    expect(wrapper.find('[data-el="strategy-list-item-1"]').exists()).toBe(true)
    await wrapper.find('[data-el="strategy-list-item-1"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-el="strategy-trade-delete"]').exists()).toBe(true)
    expect(wrapper.find('[data-el="strategy-trade-save"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('600519.SH')
  })

  it('delete click → strategyApi.delete 被调', async () => {
    const strat = { id: 7, stock_code: '600000.SH', type: 'general', status: 'active', regimes: [] }
    const { wrapper } = await _mountWithSeed([strat])

    await wrapper.find('[data-el="strategy-list-item-7"]').trigger('click')
    await flushPromises()

    await wrapper.find('[data-el="strategy-trade-delete"]').trigger('click')
    await flushPromises()
    expect(strategyApi.delete).toHaveBeenCalledWith(7)
  })

  it('save click → strategyApi.update 被调', async () => {
    const strat = { id: 1, stock_code: '600519.SH', type: 'general', status: 'active', reference_price: 10, base_volume: 100, note: 'n', regimes: [] }
    const { wrapper } = await _mountWithSeed([strat])

    await wrapper.find('[data-el="strategy-list-item-1"]').trigger('click')
    await flushPromises()

    await wrapper.find('[data-el="strategy-trade-save"]').trigger('click')
    await flushPromises()
    expect(strategyApi.update).toHaveBeenCalledWith(1, expect.objectContaining({ stock_code: '600519.SH' }))
  })

  it('submit draft → strategyApi.create 被调', async () => {
    const { wrapper } = await _mountWithSeed([])
    await wrapper.find('[data-el="strategy-trade-create"]').trigger('click')
    await flushPromises()
    wrapper.vm.draft.stock_code = '600000.SH'
    wrapper.vm.draft.reference_price = 10.0
    await wrapper.find('[data-el="strategy-trade-submit"]').trigger('click')
    await flushPromises()

    expect(strategyApi.create).toHaveBeenCalled()
  })

  it('WS strategy_update payload → store.appendAudit 被调', async () => {
    const { store } = await _mountWithSeed([])
    // 强制重新解析 ws_dispatch 的 useStrategyStore 以确保拿到 active pinia
    dispatchPayload({
      type: 'strategy_update',
      channel: 'strategy_update',
      ts: '2026-07-06T09:35:00Z',
      data: {
        strategy_id: 5,
        event: 'grid_triggered',
        regime_id: 11,
        current_price: 10.5,
        order_no: 'ORD-001',
      },
    })
    await flushPromises()

    // 直接读 auditCache（与 dispatch 写入同一个 store 实例，由 setup-view 共用 _activePinia）
    const cacheStrat = store.auditCache[5]
    expect(cacheStrat).toBeDefined()
    const trdDates = Object.keys(cacheStrat)
    expect(trdDates.length).toBe(1)
    const audits = cacheStrat[trdDates[0]]
    expect(audits.length).toBeGreaterThanOrEqual(1)
    expect(audits[0]).toMatchObject({
      trigger_type: 'grid_triggered',
      regime_id: 11,
      current_price: 10.5,
      order_no: 'ORD-001',
    })
  })

  it('WS strategy_update 缺 strategy_id → 静默丢弃', async () => {
    const { store } = await _mountWithSeed([])
    dispatchPayload({
      type: 'strategy_update',
      channel: 'strategy_update',
      ts: '2026-07-06T09:35:00Z',
      data: { event: 'grid_triggered' },
    })
    await flushPromises()

    // auditCache 应为空
    expect(Object.keys(store.auditCache).length).toBe(0)
  })

  it('tab 切换 → list 过滤（general → t0）', async () => {
    const general = { id: 1, stock_code: '600519.SH', type: 'general', status: 'active', regimes: [] }
    const t0 = { id: 2, stock_code: '000001.SZ', type: 't0', status: 'active', regimes: [] }
    const { wrapper } = await _mountWithSeed([general, t0])

    // 初始 tab=general → 显示 600519，不显示 000001
    expect(wrapper.text()).toContain('600519.SH')
    expect(wrapper.text()).not.toContain('000001.SZ')

    // 切到 t0 tab
    wrapper.vm.activeTab = 't0'
    await flushPromises()
    expect(wrapper.text()).toContain('000001.SZ')
    expect(wrapper.text()).not.toContain('600519.SH')
  })
})