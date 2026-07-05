/**
 * useT0Quota.test.js — quota 聚合 + 行内余量纯函数单测 (change-quota-frame)
 *
 * 覆盖:
 *   - aggregateQuota 输入 null/空/正常/边界
 *   - rowQuota 输入缺字段/价格=0/正常
 *   - quotaLevel 颜色阈值
 *   - useT0Quota reactive wrapper (集成 holdings store)
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import {
  aggregateQuota, rowQuota, quotaLevel, useT0Quota,
} from '../../src/composables/useT0Quota'
import { useHoldingsStore } from '../../src/stores/holdings'
import { useQuoteStore } from '../../src/stores/quote'

describe('aggregateQuota', () => {
  it('输入 null/空 → 全 0 不报错', () => {
    expect(aggregateQuota(null, null, null)).toEqual({
      cashAvail: 0, frozenCash: 0, t0AvailVol: 0, todayPnl: 0, marketValue: 0,
    })
    expect(aggregateQuota(undefined, undefined, undefined)).toEqual({
      cashAvail: 0, frozenCash: 0, t0AvailVol: 0, todayPnl: 0, marketValue: 0,
    })
  })

  it('空数据边界 → 全 0', () => {
    const r = aggregateQuota(
      { cash: 0, frozen_cash: 0, market_value: 0 },
      [],
      {}
    )
    expect(r).toEqual({
      cashAvail: 0, frozenCash: 0, t0AvailVol: 0, todayPnl: 0, marketValue: 0,
    })
  })

  it('正常输入 → 5 字段正确', () => {
    const r = aggregateQuota(
      { cash: 100000, frozen_cash: 5000, market_value: 500000 },
      [
        { stock_code: 'A', avl_vol: 1000 },
        { stock_code: 'B', avl_vol: 500 },
      ],
      { A: { realized_pnl: 800 }, B: { realized_pnl: -300 } }
    )
    expect(r.cashAvail).toBe(95000)
    expect(r.frozenCash).toBe(5000)
    expect(r.t0AvailVol).toBe(1500)
    expect(r.todayPnl).toBe(500)
    expect(r.marketValue).toBe(500000)
  })

  it('positions 非数组 → t0AvailVol = 0', () => {
    const r = aggregateQuota({ cash: 100, frozen_cash: 0 }, null, {})
    expect(r.t0AvailVol).toBe(0)
  })

  it('t0StatsMap 缺字段 → todayPnl 不报错', () => {
    const r = aggregateQuota({ cash: 0 }, [], { A: null, B: { realized_pnl: 100 } })
    expect(r.todayPnl).toBe(100)
  })

  it('t0StatsMap 缺 realized_pnl → 视作 0', () => {
    const r = aggregateQuota({ cash: 0 }, [], { A: { trade_count: 5 } })
    expect(r.todayPnl).toBe(0)
  })

  it('NaN/undefined 数字字段 → 视作 0', () => {
    const r = aggregateQuota(
      { cash: NaN, frozen_cash: undefined, market_value: 'abc' },
      [{ avl_vol: null }],
      {}
    )
    expect(r.cashAvail).toBe(0)
    expect(r.frozenCash).toBe(0)
    expect(r.marketValue).toBe(0)
    expect(r.t0AvailVol).toBe(0)
  })
})

describe('rowQuota', () => {
  it('row 缺 stock_code → 全 0', () => {
    expect(rowQuota(null, 100000, 12.5)).toEqual({ maxBuyable: 0, maxSellable: 0 })
    expect(rowQuota({}, 100000, 12.5)).toEqual({ maxBuyable: 0, maxSellable: 0 })
  })

  it('正常: cash=100000 price=12.5 → maxBuyable=8000', () => {
    const r = rowQuota({ stock_code: 'X', avl_vol: 1000 }, 100000, 12.5)
    expect(r.maxBuyable).toBe(8000)  // floor(100000/12.5/100)*100 = 80*100
    expect(r.maxSellable).toBe(1000)
  })

  it('cash=95000 price=12.5 → maxBuyable=7600', () => {
    const r = rowQuota({ stock_code: 'X', avl_vol: 100 }, 95000, 12.5)
    expect(r.maxBuyable).toBe(7600)  // floor(95000/12.5/100)*100 = 760*100
  })

  it('price=0 / null / undefined → maxBuyable=0', () => {
    expect(rowQuota({ stock_code: 'X', avl_vol: 100 }, 100000, 0).maxBuyable).toBe(0)
    expect(rowQuota({ stock_code: 'X', avl_vol: 100 }, 100000, null).maxBuyable).toBe(0)
    expect(rowQuota({ stock_code: 'X', avl_vol: 100 }, 100000, undefined).maxBuyable).toBe(0)
  })

  it('cash=0 → maxBuyable=0', () => {
    expect(rowQuota({ stock_code: 'X', avl_vol: 100 }, 0, 12.5).maxBuyable).toBe(0)
  })

  it('cash 缺字段 → 视作 0', () => {
    expect(rowQuota({ stock_code: 'X', avl_vol: 100 }, undefined, 12.5).maxBuyable).toBe(0)
    expect(rowQuota({ stock_code: 'X', avl_vol: 100 }, null, 12.5).maxBuyable).toBe(0)
  })

  it('可卖 = avl_vol 缺字段 → 0', () => {
    expect(rowQuota({ stock_code: 'X' }, 100000, 12.5).maxSellable).toBe(0)
    expect(rowQuota({ stock_code: 'X', avl_vol: null }, 100000, 12.5).maxSellable).toBe(0)
  })

  it('price < cash/LOT_SIZE → maxBuyable=0 (1 手都买不起)', () => {
    // cash=500 price=12.5 → 500/12.5/100 = 0.4 → floor=0
    expect(rowQuota({ stock_code: 'X', avl_vol: 0 }, 500, 12.5).maxBuyable).toBe(0)
  })
})

describe('quotaLevel', () => {
  it('≥ 1000 → high', () => {
    expect(quotaLevel(1000)).toBe('high')
    expect(quotaLevel(5000)).toBe('high')
  })
  it('100-999 → mid', () => {
    expect(quotaLevel(100)).toBe('mid')
    expect(quotaLevel(999)).toBe('mid')
    expect(quotaLevel(500)).toBe('mid')
  })
  it('1-99 → low', () => {
    expect(quotaLevel(1)).toBe('low')
    expect(quotaLevel(99)).toBe('low')
    expect(quotaLevel(50)).toBe('low')
  })
  it('0 / 负 → none', () => {
    expect(quotaLevel(0)).toBe('none')
    expect(quotaLevel(-1)).toBe('none')
    expect(quotaLevel(undefined)).toBe('none')
    expect(quotaLevel(null)).toBe('none')
    expect(quotaLevel(NaN)).toBe('none')
  })
})

describe('useT0Quota reactive wrapper', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('aggregate 自动从 holdings 拉 cachedAsset + positions', () => {
    const h = useHoldingsStore()
    h.cachedAsset = { cash: 100000, frozen_cash: 5000, market_value: 500000 }
    h.positions = [{ stock_code: 'A', avl_vol: 1000 }]

    const ref = { value: {} }
    const { aggregate } = useT0Quota(ref)
    expect(aggregate.value.cashAvail).toBe(95000)
    expect(aggregate.value.t0AvailVol).toBe(1000)
  })

  it('t0StatsMap 传入 → todayPnl 聚合', () => {
    const h = useHoldingsStore()
    h.cachedAsset = { cash: 0 }
    h.positions = []

    const ref = { value: { A: { realized_pnl: 1000 }, B: { realized_pnl: -200 } } }
    const { aggregate } = useT0Quota(ref)
    expect(aggregate.value.todayPnl).toBe(800)
  })

  it('cachedAsset.cash 变化 → aggregate 重算', () => {
    const h = useHoldingsStore()
    h.cachedAsset = { cash: 100000, frozen_cash: 0 }
    h.positions = []

    const ref = { value: {} }
    const { aggregate } = useT0Quota(ref)
    expect(aggregate.value.cashAvail).toBe(100000)

    h.cachedAsset = { cash: 50000, frozen_cash: 0 }
    expect(aggregate.value.cashAvail).toBe(50000)
  })

  it('rowQuota 依赖 last_price → quoteStore 更新时重算', () => {
    const h = useHoldingsStore()
    const q = useQuoteStore()
    h.cachedAsset = { cash: 100000, frozen_cash: 0 }
    h.positions = [{ stock_code: 'A', avl_vol: 1000 }]

    // mock quoteStore.byCode 更新
    q.byCode.set('A', { last_price: 12.5 })

    const ref = { value: {} }
    const { rowQuota } = useT0Quota(ref)
    expect(rowQuota({ stock_code: 'A', avl_vol: 1000 }).maxBuyable).toBe(8000)

    // 更新 last_price → maxBuyable 重算
    q.byCode.set('A', { last_price: 25 })
    expect(rowQuota({ stock_code: 'A', avl_vol: 1000 }).maxBuyable).toBe(4000)
  })

  it('rowQuota 缺 price → maxBuyable=0', () => {
    const h = useHoldingsStore()
    h.cachedAsset = { cash: 100000 }
    h.positions = []

    const ref = { value: {} }
    const { rowQuota } = useT0Quota(ref)
    expect(rowQuota({ stock_code: 'A', avl_vol: 1000 }).maxBuyable).toBe(0)
  })
})