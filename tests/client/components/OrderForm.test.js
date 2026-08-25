/**
 * OrderForm.test.js — 下单表单 委托数量分数快捷按钮单测 (REQ-FE-543)
 *
 * 验证:
 *   - 5 个分数按钮渲染 (1/10, 1/5, 1/4, 1/2, 1/1)
 *   - 买入 1/2: cash/px/unit → 整手向下取整
 *   - 卖出 1/2: avl_vol/unit → 整手向上取整
 *   - 不足 1 手 → 0 (按钮带提示)
 *   - trade_unit != 1 (跨境 ETF) → 按 trade_unit 整手
 *   - 切换买卖方向后重新计算 (不继承上一方向值)
 *   - 无可用时按钮 disabled
 */
// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from 'vitest'

vi.mock('@/api', () => {
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

import '../setup-view'
import { mountView } from '../setup-view'
import OrderForm from '@/components/OrderForm.vue'
import { useAssetStore } from '@/stores/asset'
import { useHoldingsStore } from '@/stores/holdings'
import { useQuoteStore } from '@/stores/quote'
import { useStocksStore } from '@/stores/stocks'

// 子组件 stub — StockCodePicker 内部走 el-autocomplete, 测试只关心 OrderForm 行为
const StubStockCodePicker = {
  name: 'StockCodePicker',
  template: '<input class="stock-code-picker-stub" :value="modelValue" @input="onInput($event)" />',
  props: ['modelValue'],
  emits: ['update:model-value', 'select', 'blur'],
  methods: {
    applyStockCode(code) { this.$emit('update:model-value', code) },
    onInput(e) { this.$emit('update:model-value', e.target.value) },
  }
}
const StubPriceTypeInput = {
  name: 'PriceTypeInput',
  template: '<div class="price-type-input-stub" />',
  props: ['price', 'priceType', 'stockCode'],
  emits: ['update:price', 'update:price-type'],
}

const FIX_PRICE = 11  // PriceType.FIX_PRICE

function seedStores({
  stockCode = '600519.SH',
  cash = 0,
  positions = [],
  lastPrice = 0,
  tradeUnit = 100,
}) {
  // asset store 是 writable computed → set 转发到 holdings.cachedAsset
  const assetStore = useAssetStore()
  assetStore.asset = { cash, total_asset: cash, available: cash, frozen_cash: 0 }

  // holdings.positions 是 ref([]), 直接赋值即可
  const holdings = useHoldingsStore()
  holdings.positions = positions

  // quote store: 用 update(payload) 写 last_price
  if (stockCode && lastPrice > 0) {
    const quoteStore = useQuoteStore()
    quoteStore.update({ stock_code: stockCode, last_price: lastPrice })
  }

  // stocks store: cacheLoaded + cacheMap.set
  if (stockCode && tradeUnit) {
    const stocksStore = useStocksStore()
    stocksStore.cacheLoaded = true
    stocksStore.cacheMap.set(stockCode, {
      stock_code: stockCode,
      trade_unit: tradeUnit,
      scale: 2,
      stktype: 0,
    })
  }
}

function mountOrderForm(initialStockCode = '600519.SH') {
  return mountView(OrderForm, {
    props: { onSubmit: vi.fn(), defaultStockCode: initialStockCode },
    stubs: {
      StockCodePicker: StubStockCodePicker,
      PriceTypeInput: StubPriceTypeInput,
    }
  })
}

// 设置 form 字段 (script setup reactive, 可通过 wrapper.vm.form 直接改)
function setForm(wrapper, fields) {
  Object.assign(wrapper.vm.form, fields)
}

describe('OrderForm — 委托数量分数快捷按钮 (REQ-FE-543)', () => {
  let wrapper

  beforeEach(() => {
    vi.clearAllMocks()
    wrapper = mountOrderForm('600519.SH')
  })

  it('renders 5 个分数按钮 1/10, 1/5, 1/4, 1/2, 1/1', () => {
    const btns = wrapper.findAll('.volume-quick .quick-btn')
    expect(btns).toHaveLength(5)
    expect(btns.map(b => b.text())).toEqual(['1/10', '1/5', '1/4', '1/2', '1/1'])
  })

  // ---------- 买入 (order_type=23) ----------
  describe('买入 (order_type=23, 买向下取整)', () => {
    beforeEach(async () => {
      seedStores({
        stockCode: '600519.SH',
        cash: 50000,
        lastPrice: 10,        // 可买 50000/10 = 5000 股
        tradeUnit: 100,
      })
      // 默认 order_type='23' (buy), price_type=FIX_PRICE(11); 改 stock_code + price
      setForm(wrapper, { stock_code: '600519.SH', order_type: '23', price_type: FIX_PRICE, price: 10 })
      await wrapper.vm.$nextTick()
    })

    it('买 1/2 → form.volume = 2500 (5000 × 0.5, trade_unit=100 整手)', async () => {
      const btn = wrapper.findAll('.volume-quick .quick-btn').find(b => b.text() === '1/2')
      await btn.trigger('click')
      expect(wrapper.vm.form.volume).toBe(2500)
    })

    it('买 1/10 → form.volume = 500 (5000 × 0.1, 整手 100 整除)', async () => {
      const btn = wrapper.findAll('.volume-quick .quick-btn').find(b => b.text() === '1/10')
      await btn.trigger('click')
      expect(wrapper.vm.form.volume).toBe(500)
    })

    it('买 1/1 → form.volume = 5000 (整手)', async () => {
      const btn = wrapper.findAll('.volume-quick .quick-btn').find(b => b.text() === '1/1')
      await btn.trigger('click')
      expect(wrapper.vm.form.volume).toBe(5000)
    })

    it('买 cash 不足 1 手 → 按钮 disabled (UX: 不可下单)', async () => {
      seedStores({
        stockCode: '600519.SH',
        cash: 500,            // 50 股 < 100, 不足 1 手
        lastPrice: 10,
        tradeUnit: 100,
      })
      setForm(wrapper, { stock_code: '600519.SH', order_type: '23', price_type: FIX_PRICE, price: 10 })
      await wrapper.vm.$nextTick()
      // 验证 availableTradeQty 实际计算结果为 0 (买向下取整)
      expect(wrapper.vm.availableTradeQty).toBe(0)
      // 验证所有分数按钮 disabled (可用为 0 → 不可下单)
      const btns = wrapper.findAll('.volume-quick .quick-btn')
      btns.forEach(b => expect(b.attributes('disabled')).toBeDefined())
    })

    it('买 trade_unit=1 (跨境 ETF) → 不取整, 1/2 = 2500', async () => {
      seedStores({
        stockCode: '510300.SH',
        cash: 50000,
        lastPrice: 10,
        tradeUnit: 1,         // 1 股 1 手
      })
      setForm(wrapper, { stock_code: '510300.SH', order_type: '23', price_type: FIX_PRICE, price: 10 })
      await wrapper.vm.$nextTick()
      const btn = wrapper.findAll('.volume-quick .quick-btn').find(b => b.text() === '1/2')
      await btn.trigger('click')
      expect(wrapper.vm.form.volume).toBe(2500)
    })
  })

  // ---------- 卖出 (order_type=24) ----------
  describe('卖出 (order_type=24, 卖向上取整)', () => {
    beforeEach(async () => {
      seedStores({
        stockCode: '600519.SH',
        positions: [{ stock_code: '600519.SH', vol: 3000, avl_vol: 3000 }],
        tradeUnit: 100,
      })
      setForm(wrapper, { stock_code: '600519.SH', order_type: '24' })
      await wrapper.vm.$nextTick()
    })

    it('卖 1/2 → form.volume = 1500 (3000 × 0.5, 整手)', async () => {
      const btn = wrapper.findAll('.volume-quick .quick-btn').find(b => b.text() === '1/2')
      await btn.trigger('click')
      expect(wrapper.vm.form.volume).toBe(1500)
    })

    it('卖 1/1 → form.volume = 3000 (全额)', async () => {
      const btn = wrapper.findAll('.volume-quick .quick-btn').find(b => b.text() === '1/1')
      await btn.trigger('click')
      expect(wrapper.vm.form.volume).toBe(3000)
    })

    it('卖 1/10 avl=85 不足 1 手 → form.volume = 0', async () => {
      seedStores({
        stockCode: '600519.SH',
        positions: [{ stock_code: '600519.SH', vol: 85, avl_vol: 85 }],
        tradeUnit: 100,
      })
      setForm(wrapper, { stock_code: '600519.SH', order_type: '24' })
      await wrapper.vm.$nextTick()
      const btn = wrapper.findAll('.volume-quick .quick-btn').find(b => b.text() === '1/10')
      await btn.trigger('click')
      expect(wrapper.vm.form.volume).toBe(0)
    })

    it('卖 不超 available (向上取整保护) — avl=1000, unit=300, 1/1 → 900 (不超 1000)', async () => {
      // avl=1000, unit=300: ceil(1000/300)*300 = 1200 > 1000, fallback floor → 900
      seedStores({
        stockCode: '600519.SH',
        positions: [{ stock_code: '600519.SH', vol: 1000, avl_vol: 1000 }],
        tradeUnit: 300,
      })
      setForm(wrapper, { stock_code: '600519.SH', order_type: '24' })
      await wrapper.vm.$nextTick()
      const btn = wrapper.findAll('.volume-quick .quick-btn').find(b => b.text() === '1/1')
      await btn.trigger('click')
      expect(wrapper.vm.form.volume).toBe(900)
    })
  })

  // ---------- 方向切换 + 禁用态 ----------
  describe('方向切换 / 禁用态', () => {
    it('切换买卖方向后, 分数按钮重新计算 (不继承 buy 值)', async () => {
      // 先 seed 买入 → 点 1/2 → 2500
      seedStores({
        stockCode: '600519.SH',
        cash: 50000,
        lastPrice: 10,
        tradeUnit: 100,
      })
      setForm(wrapper, { stock_code: '600519.SH', order_type: '23', price_type: FIX_PRICE, price: 10 })
      await wrapper.vm.$nextTick()
      let btn = wrapper.findAll('.volume-quick .quick-btn').find(b => b.text() === '1/2')
      await btn.trigger('click')
      expect(wrapper.vm.form.volume).toBe(2500)

      // 切到卖出, seed avl=1000
      seedStores({
        stockCode: '600519.SH',
        positions: [{ stock_code: '600519.SH', vol: 1000, avl_vol: 1000 }],
        tradeUnit: 100,
      })
      setForm(wrapper, { order_type: '24' })
      await wrapper.vm.$nextTick()
      btn = wrapper.findAll('.volume-quick .quick-btn').find(b => b.text() === '1/2')
      await btn.trigger('click')
      // 卖出 1/2 = 500 (floor(500/100)*100 = 500, ceil 同样)
      expect(wrapper.vm.form.volume).toBe(500)
    })

    it('无可用持仓 (卖, 无 position) → 按钮 disabled', async () => {
      // 重置: 卖出方向, 无持仓
      setForm(wrapper, { stock_code: '600519.SH', order_type: '24' })
      await wrapper.vm.$nextTick()
      const btns = wrapper.findAll('.volume-quick .quick-btn')
      btns.forEach(b => expect(b.attributes('disabled')).toBeDefined())
    })
  })
})