/**
 * HoldingsPanel.test.js — 交易下单页持仓 mini 面板单测
 *
 * 覆盖 (REQ-FE-557 position-filter-small-holdings 2026-10-23):
 *   - 过滤小持仓 checkbox 默认勾上
 *   - onMounted 读 sysconfig `position_filter_min_vol` → 写入 minVolThreshold
 *   - 过滤语义: vol <= 阈值 的行隐藏 (含等号); 阈值 0 = 只隐藏 0 持仓行
 *   - 取消勾选 → 全部显示
 *   - 读取失败 (403/404/网络) → 降级阈值 0, 不阻塞面板
 *   - keyword 过滤与小持仓过滤 AND 叠加
 *   - totalMv 随过滤结果联动
 */
// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from 'vitest'

vi.mock('@/api', () => ({
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

vi.mock('@/api/sysconfig', () => ({
  sysconfigApi: { get: vi.fn(), list: vi.fn(), upsert: vi.fn(), update: vi.fn(), remove: vi.fn() },
}))

import '../../setup-view'
import { mountView, flushPromises } from '../../setup-view'
import { useHoldingsStore } from '@/stores/holdings'
import { useQuoteStore } from '@/stores/quote'
import { sysconfigApi } from '@/api/sysconfig'
import HoldingsPanel from '@/components/trade/HoldingsPanel.vue'

const activeDay = '20260705'

function seedPositions(rows) {
  const h = useHoldingsStore()
  h.activeTrdDate = activeDay
  h.positions = rows
}

/** 灌行情 (totalMv 走 holdingsStore.getMarketValue → quoteStore.getLastPrice) */
function seedQuotes(prices) {
  const q = useQuoteStore()
  for (const [code, price] of Object.entries(prices)) {
    q.update({ stock_code: code, last_price: price })
  }
}

function pos(code, vol, price = 10) {
  return {
    stock_code: code,
    vol,
    avl_vol: vol,
    last_vol: vol,
    cost_price: price,
    market_value: vol * price,
  }
}

describe('HoldingsPanel — 过滤小持仓 (REQ-FE-557)', () => {
  let wrapper

  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(sysconfigApi.get).mockResolvedValue({ cfg_val: '0' })
    seedPositions([])
  })

  it('mounts 且渲染 tp-header', async () => {
    wrapper = mountView(HoldingsPanel)
    await flushPromises()
    expect(wrapper.exists()).toBe(true)
    expect(wrapper.find('.tp-header').exists()).toBe(true)
  })

  it('checkbox 默认勾上 (filterSmall 初值 true)', async () => {
    wrapper = mountView(HoldingsPanel)
    await flushPromises()
    expect(wrapper.vm.filterSmall).toBe(true)
    expect(wrapper.find('.hp-filter-small').exists()).toBe(true)
  })

  it('onMounted 读 position_filter_min_vol 并写入 minVolThreshold', async () => {
    vi.mocked(sysconfigApi.get).mockResolvedValue({ cfg_val: '100' })
    wrapper = mountView(HoldingsPanel)
    await flushPromises()
    expect(sysconfigApi.get).toHaveBeenCalledWith('position_filter_min_vol')
    expect(wrapper.vm.minVolThreshold).toBe(100)
  })

  it('阈值 0 → 只隐藏 vol=0 的行', async () => {
    seedPositions([pos('600000.SH', 0), pos('600519.SH', 100)])
    wrapper = mountView(HoldingsPanel)
    await flushPromises()
    expect(wrapper.vm.filteredPositions.length).toBe(1)
    expect(wrapper.vm.filteredPositions[0].stock_code).toBe('600519.SH')
  })

  it('阈值 100 → vol <= 100 隐藏 (含等号)', async () => {
    vi.mocked(sysconfigApi.get).mockResolvedValue({ cfg_val: '100' })
    seedPositions([pos('600000.SH', 100), pos('600519.SH', 101), pos('000001.SZ', 500)])
    wrapper = mountView(HoldingsPanel)
    await flushPromises()
    expect(wrapper.vm.minVolThreshold).toBe(100)
    expect(wrapper.vm.filteredPositions.map((p) => p.stock_code)).toEqual(['600519.SH', '000001.SZ'])
  })

  it('取消勾选 → 全部显示', async () => {
    vi.mocked(sysconfigApi.get).mockResolvedValue({ cfg_val: '100' })
    seedPositions([pos('600000.SH', 10), pos('600519.SH', 500)])
    wrapper = mountView(HoldingsPanel)
    await flushPromises()
    expect(wrapper.vm.filteredPositions.length).toBe(1)
    wrapper.vm.filterSmall = false
    await flushPromises()
    expect(wrapper.vm.filteredPositions.length).toBe(2)
  })

  it('读取失败 → 降级阈值 0, 面板不崩', async () => {
    vi.mocked(sysconfigApi.get).mockRejectedValue(new Error('403'))
    seedPositions([pos('600000.SH', 100), pos('600519.SH', 0)])
    wrapper = mountView(HoldingsPanel)
    await flushPromises()
    expect(wrapper.vm.minVolThreshold).toBe(0)
    expect(wrapper.vm.filteredPositions.length).toBe(1)
    expect(wrapper.vm.filteredPositions[0].stock_code).toBe('600000.SH')
  })

  it('非法阈值 (非数字) → 保持默认 0', async () => {
    vi.mocked(sysconfigApi.get).mockResolvedValue({ cfg_val: 'abc' })
    wrapper = mountView(HoldingsPanel)
    await flushPromises()
    expect(wrapper.vm.minVolThreshold).toBe(0)
  })

  it('keyword 过滤与小持仓过滤 AND 叠加', async () => {
    vi.mocked(sysconfigApi.get).mockResolvedValue({ cfg_val: '100' })
    seedPositions([pos('600000.SH', 10), pos('600519.SH', 500), pos('600036.SH', 500)])
    wrapper = mountView(HoldingsPanel)
    await flushPromises()
    wrapper.vm.keyword = '6005'
    await flushPromises()
    expect(wrapper.vm.filteredPositions.map((p) => p.stock_code)).toEqual(['600519.SH'])
  })

  it('totalMv 随过滤结果联动', async () => {
    vi.mocked(sysconfigApi.get).mockResolvedValue({ cfg_val: '100' })
    seedPositions([pos('600000.SH', 100, 10), pos('600519.SH', 500, 10)])
    seedQuotes({ '600000.SH': 10, '600519.SH': 10 })
    wrapper = mountView(HoldingsPanel)
    await flushPromises()
    expect(wrapper.vm.totalMv).toBe(5000)
    wrapper.vm.filterSmall = false
    await flushPromises()
    expect(wrapper.vm.totalMv).toBe(6000)
  })

  it('勾选时显示阈值提示文案 (显示大于N股持仓)', async () => {
    vi.mocked(sysconfigApi.get).mockResolvedValue({ cfg_val: '100' })
    wrapper = mountView(HoldingsPanel)
    await flushPromises()
    expect(wrapper.find('.hp-threshold').text()).toContain('显示大于100股持仓')
    wrapper.vm.filterSmall = false
    await flushPromises()
    expect(wrapper.find('.hp-threshold').exists()).toBe(false)
  })
})
