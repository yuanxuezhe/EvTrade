/**
 * T0Trade.test.js — 快速做T view 单测 (v127 重写)
 *
 * 旧版本 (v55 之前) 断言 quotaForRow / PCT_OPTIONS / _moveSelection 等已删除 API,
 * 全部失效。本文件对齐 v127 现状:
 *   - 主表 task 视角 (taskRows 来自 t0TasksStore.loadTasks)
 *   - 选中联动 (onTaskRowClick / selectedTaskId / selectedStockCode / ptRowClass)
 *   - v127 价格 + 价格类型 (PriceTypeInput): 类型切换自动重填 orderPrice
 *   - v127 买/卖按钮联动选中 (未选中先选 → 等 watcher → 下单)
 *   - computeOrderVolume 三模式 (pct / qty / amount)
 *   - 配平差值 (_taskNetDiff → balanceBtnLabel / computeRowBalanceDiff)
 *   - 下半委托表过滤 (task_id 匹配 + 排除 strategy_type=2 策略母单子单)
 */
// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { nextTick } from 'vue'

vi.mock('@/api', () => {
  const fn = () => vi.fn()
  return {
    api: {
      getOrders: fn(), getTrades: fn(), getAsset: fn(), getHoldings: fn(),
      getPositions: fn(), getActiveDay: fn(),
      placeOrder: fn().mockResolvedValue({ code: 0, list: [{}] }),
      cancelOrder: fn(), adjustAsset: fn(), adjustPosition: fn(),
      adminReconcile: fn(),
    },
    authApi: { login: fn(), logout: fn() },
    userApi: { list: fn(), create: fn(), update: fn(), delete: fn() },
    http: { interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } } },
    setUnauthorizedHandler: vi.fn(),
    tokenStorage: { get: vi.fn(() => ''), set: vi.fn(), clear: vi.fn() },
    createWSConnection: vi.fn(),
  }
})

vi.mock('@/api/t0_tasks', () => ({
  t0TasksApi: {
    // 注意: vi.mock 工厂被 hoist 到文件顶部, 不能引用外层 const → 数据内联
    list: vi.fn().mockResolvedValue([
      { id: 1, stock_code: '600030.SH', status: 'active', base_volume: 0, target_volume: 0 },
      { id: 2, stock_code: '000001.SZ', status: 'active', base_volume: 0, target_volume: 0 },
      { id: 3, stock_code: '600519.SH', status: 'archived', base_volume: 0, target_volume: 0 },
    ]),
    overview: vi.fn().mockResolvedValue({}),
    create: vi.fn(), update: vi.fn(), remove: vi.fn(),
    close: vi.fn(), stats: vi.fn(),
  },
}))

import '../setup-view'
import { mountView, flushPromises } from '../setup-view'
import { useHoldingsStore } from '@/stores/holdings'
import { useQuoteStore } from '@/stores/quote'
import { useOrderStore } from '@/stores/order'
import { PriceType } from '@/constants/priceType'
import T0Trade from '@/views/T0Trade.vue'

const POSITIONS = [
  { stock_code: '600030.SH', stock_name: '中信证券', vol: 1000, avl_vol: 1000, last_vol: 1000 },
  { stock_code: '000001.SZ', stock_name: '平安银行', vol: 500, avl_vol: 500, last_vol: 500 },
]

function seedStores() {
  const h = useHoldingsStore()
  h.positions = POSITIONS
  h.cachedAsset = { cash: 100000, available: 100000, frozen_cash: 0 }
  h.orders = []

  const q = useQuoteStore()
  // 上海: 带 5 档 → 市价保护限价可算 (store 解包后 byCode 就是 Map)
  q.byCode.set('600030.SH', {
    last_price: 13.0,
    prev_close: 12.5,
    ask_prices: [13.01, 13.02, 13.03, 13.04, 13.05],
    bid_prices: [12.99, 12.98, 12.97, 12.96, 12.95],
  })
  // 深圳: 无需保护限价
  q.byCode.set('000001.SZ', { last_price: 11.5, prev_close: 11.0 })
  return { h, q }
}

async function mountReady() {
  const wrapper = mountView(T0Trade)
  await flushPromises()
  return wrapper
}

describe('T0Trade', () => {
  beforeEach(() => {
    seedStores()
  })

  it('mounts', async () => {
    const wrapper = await mountReady()
    expect(wrapper.find('.t0-trade').exists()).toBe(true)
  })

  it('taskRows 来自 t0TasksStore.loadTasks', async () => {
    const wrapper = await mountReady()
    expect(wrapper.vm.taskRows.length).toBe(3)
  })

  it('默认选中第一条 task', async () => {
    const wrapper = await mountReady()
    expect(wrapper.vm.selectedTaskId).toBe(1)
    expect(wrapper.vm.selectedStockCode).toBe('600030.SH')
  })

  it('onTaskRowClick: 再点已选中行 → 取消选中', async () => {
    const wrapper = await mountReady()
    wrapper.vm.onTaskRowClick({ id: 1 })
    expect(wrapper.vm.selectedTaskId).toBe(null)
    wrapper.vm.onTaskRowClick({ id: 2 })
    expect(wrapper.vm.selectedTaskId).toBe(2)
    expect(wrapper.vm.selectedStockCode).toBe('000001.SZ')
  })

  it('ptRowClass: 选中行 is-selected', async () => {
    const wrapper = await mountReady()
    expect(wrapper.vm.ptRowClass({ row: { id: 1 } })).toContain('is-selected')
    expect(wrapper.vm.ptRowClass({ row: { id: 2 } })).not.toContain('is-selected')
  })

  // ─── v127: 价格 + 价格类型联动 ───

  it('默认价格类型 = 市价 (44)', async () => {
    const wrapper = await mountReady()
    expect(wrapper.vm.orderPriceTypeCode).toBe(PriceType.MARKET_PEER_PRICE_FIRST)
  })

  it('切限价 (11) → orderPrice 自动填最新价', async () => {
    const wrapper = await mountReady()
    wrapper.vm.orderPriceTypeCode = PriceType.FIX_PRICE
    await nextTick()
    expect(wrapper.vm.orderPrice).toBe(13.0)
  })

  it('切最新价 (5) → orderPrice = 0', async () => {
    const wrapper = await mountReady()
    wrapper.vm.orderPriceTypeCode = PriceType.LATEST_PRICE
    await nextTick()
    expect(wrapper.vm.orderPrice).toBe(0)
  })

  it('市价 (44) + 上交所 → orderPrice = 对手盘第 5 档 (卖五)', async () => {
    const wrapper = await mountReady()
    wrapper.vm.orderPriceTypeCode = PriceType.LATEST_PRICE
    await nextTick()
    wrapper.vm.orderPriceTypeCode = PriceType.MARKET_PEER_PRICE_FIRST
    await nextTick()
    expect(wrapper.vm.orderPrice).toBe(13.05)
  })

  it('市价 (44) + 深交所 → orderPrice = 0', async () => {
    const wrapper = await mountReady()
    wrapper.vm.selectedTaskId = 2   // 000001.SZ
    await nextTick()
    expect(wrapper.vm.selectedStockCode).toBe('000001.SZ')
    expect(wrapper.vm.orderPrice).toBe(0)
  })

  it('切 task → orderPrice 按新标的重填 (限价)', async () => {
    const wrapper = await mountReady()
    wrapper.vm.orderPriceTypeCode = PriceType.FIX_PRICE
    await nextTick()
    expect(wrapper.vm.orderPrice).toBe(13.0)
    wrapper.vm.selectedTaskId = 2
    await nextTick()
    expect(wrapper.vm.orderPrice).toBe(11.5)
  })

  it('未选中标的 → orderPrice 归零', async () => {
    const wrapper = await mountReady()
    wrapper.vm.selectedTaskId = null
    await nextTick()
    expect(wrapper.vm.orderPrice).toBe(0)
  })

  // ─── v127: 买/卖按钮联动选中 ───

  it('onBuyTask: 未选中行 → 隐式选中 + 价格切到该标的', async () => {
    const wrapper = await mountReady()
    const orderStore = useOrderStore()
    orderStore.placeOrder = vi.fn().mockResolvedValue([{}])
    wrapper.vm.orderPriceTypeCode = PriceType.FIX_PRICE
    await nextTick()

    await wrapper.vm.onBuyTask({ id: 2, stock_code: '000001.SZ', status: 'active' })
    expect(wrapper.vm.selectedTaskId).toBe(2)
    expect(wrapper.vm.orderPrice).toBe(11.5)
    expect(orderStore.placeOrder).toHaveBeenCalledOnce()
    expect(orderStore.placeOrder.mock.calls[0][0]).toMatchObject({
      stock_code: '000001.SZ', order_type: '23', price: 11.5, strategy_type: 1,
    })
  })

  it('onBuyTask: 已选中行 → 不重置用户手改的价格', async () => {
    const wrapper = await mountReady()
    const orderStore = useOrderStore()
    orderStore.placeOrder = vi.fn().mockResolvedValue([{}])
    wrapper.vm.orderPriceTypeCode = PriceType.FIX_PRICE
    await nextTick()
    wrapper.vm.orderPrice = 12.34   // 用户手改

    await wrapper.vm.onBuyTask({ id: 1, stock_code: '600030.SH', status: 'active' })
    expect(wrapper.vm.orderPrice).toBe(12.34)
    expect(orderStore.placeOrder.mock.calls[0][0].price).toBe(12.34)
  })

  it('onSellTask: order_type = 24', async () => {
    const wrapper = await mountReady()
    const orderStore = useOrderStore()
    orderStore.placeOrder = vi.fn().mockResolvedValue([{}])

    await wrapper.vm.onSellTask({ id: 1, stock_code: '600030.SH', status: 'active' })
    expect(orderStore.placeOrder.mock.calls[0][0].order_type).toBe('24')
  })

  it('canOpRow: archived / 无标的 → 不可下单', async () => {
    const wrapper = await mountReady()
    expect(wrapper.vm.canOpRow({ status: 'active', stock_code: '600030.SH' })).toBe(true)
    expect(wrapper.vm.canOpRow({ status: 'archived', stock_code: '600030.SH' })).toBe(false)
    expect(wrapper.vm.canOpRow({ status: 'active', stock_code: '' })).toBe(false)
  })

  // ─── computeOrderVolume 三模式 ───

  it('computeOrderVolume qty 模式: 直接用股数', async () => {
    const wrapper = await mountReady()
    wrapper.vm.globalMode = 'qty'
    wrapper.vm.globalQtyInput = 300
    await nextTick()
    expect(wrapper.vm.computeOrderVolume('600030.SH', '买').volume).toBe(300)
  })

  it('computeOrderVolume amount 模式: 金额 / 最新价 取整', async () => {
    const wrapper = await mountReady()
    wrapper.vm.globalMode = 'amount'
    wrapper.vm.globalAmountInput = 13000   // / 13.0 = 1000 股
    await nextTick()
    expect(wrapper.vm.computeOrderVolume('600030.SH', '买').volume).toBe(1000)
  })

  it('computeOrderVolume pct 模式: 卖按持仓基数', async () => {
    const wrapper = await mountReady()
    wrapper.vm.globalMode = 'pct'
    wrapper.vm.globalPctInput = 25
    wrapper.vm.globalQtyBase = 'last_vol'
    await nextTick()
    // last_vol=1000 × 25% = 250 → floor 到 trade_unit(默认 1) = 250
    expect(wrapper.vm.computeOrderVolume('600030.SH', '卖').volume).toBe(250)
  })

  it('computeOrderVolume: 无 stock_code → volume 0', async () => {
    const wrapper = await mountReady()
    expect(wrapper.vm.computeOrderVolume('', '买').volume).toBe(0)
  })

  // ─── 配平差值 ───

  it('balanceBtnLabel: 净差=0 → 已平衡', async () => {
    const wrapper = await mountReady()
    expect(wrapper.vm.balanceBtnLabel(1)).toBe('已平衡')
    expect(wrapper.vm.computeRowBalanceDiff(1)).toBe(0)
  })

  it('balanceBtnLabel: 多买 → 补卖 N', async () => {
    const h = useHoldingsStore()
    h.orders = [{ task_id: 1, order_type: '23', traded_volume: 500, stock_code: '600030.SH' }]
    const wrapper = await mountReady()
    expect(wrapper.vm.computeRowBalanceDiff(1)).toBe(500)
    expect(wrapper.vm.balanceBtnLabel(1)).toBe('补卖 500')
  })

  it('balanceBtnLabel: 多卖 → 补买 N', async () => {
    const h = useHoldingsStore()
    h.orders = [{ task_id: 1, order_type: '24', traded_volume: 300, stock_code: '600030.SH' }]
    const wrapper = await mountReady()
    expect(wrapper.vm.balanceBtnLabel(1)).toBe('补买 300')
  })

  it('配平差值排除 strategy_type=2 (策略母单子单)', async () => {
    const h = useHoldingsStore()
    h.orders = [
      { task_id: 1, order_type: '23', traded_volume: 500, strategy_type: 1 },
      { task_id: 1, order_type: '23', traded_volume: 999, strategy_type: 2 },
    ]
    const wrapper = await mountReady()
    expect(wrapper.vm.computeRowBalanceDiff(1)).toBe(500)
  })

  // ─── 下半委托表 ───

  it('filteredTaskOrders: 按 task_id 过滤 + 排除 strategy_type=2 + 时间倒序', async () => {
    const h = useHoldingsStore()
    h.orders = [
      { task_id: 1, order_no: 'A', order_time: '09:30:00' },
      { task_id: 1, order_no: 'B', order_time: '10:00:00' },
      { task_id: 2, order_no: 'C', order_time: '09:40:00' },
      { task_id: 1, order_no: 'D', order_time: '11:00:00', strategy_type: 2 },
    ]
    const wrapper = await mountReady()
    const list = wrapper.vm.filteredTaskOrders
    expect(list.map(o => o.order_no)).toEqual(['B', 'A'])
  })

  it('canCancel: 仅 已报(50)/部成(55) 可撤, 撤单行(order_flag=1) 不可再撤', async () => {
    const wrapper = await mountReady()
    expect(wrapper.vm.canCancel({ status: '50' })).toBe(true)
    expect(wrapper.vm.canCancel({ status: '55' })).toBe(true)
    expect(wrapper.vm.canCancel({ status: '56' })).toBe(false)
    expect(wrapper.vm.canCancel({ status: '50', order_flag: 1 })).toBe(false)
    expect(wrapper.vm.canCancel(null)).toBe(false)
  })

  it('statusLabel / statusTagType', async () => {
    const wrapper = await mountReady()
    expect(wrapper.vm.statusLabel('active')).toBe('活跃')
    expect(wrapper.vm.statusLabel('archived')).toBe('已归档')
    expect(wrapper.vm.statusTagType('active')).toBe('primary')
    expect(wrapper.vm.statusTagType('archived')).toBe('danger')
  })
})
