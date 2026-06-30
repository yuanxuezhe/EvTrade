/**
 * useQuickT0.js 测试 (M-008, 8 用例)
 *
 * 覆盖 SPEC §10 验收清单:
 *   - 100 股整百截断
 *   - 0 持仓买按钮禁用
 *   - 4 档百分比 (25/50/75/100) 计算正确
 *   - 3 档价格 (last/market/bidask) 解析正确
 *   - localStorage 持久化
 *   - buildQuickOrder 端到端
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import {
  PCT_OPTIONS,
  PRICE_TYPE_OPTIONS,
  DEFAULT_PCT,
  DEFAULT_PRICE_TYPE,
  roundToLot,
  calcBuyQty,
  calcSellQty,
  calcQuickQty,
  resolvePrice,
  isBuyDisabled,
  validateQuick,
  loadQuickDefaults,
  saveQuickDefaults,
  buildQuickOrder,
} from '../../src/composables/useQuickT0'


describe('useQuickT0 常量', () => {
  it('PCT_OPTIONS 4 档 (用户拍板)', () => {
    expect(PCT_OPTIONS).toEqual([25, 50, 75, 100])
  })
  it('PRICE_TYPE_OPTIONS 3 档 (用户拍板)', () => {
    expect(PRICE_TYPE_OPTIONS.map((o) => o.value)).toEqual(['last', 'market', 'bidask'])
    expect(PRICE_TYPE_OPTIONS[0].priceTypeCode).toBe(11)  // last 限价
    expect(PRICE_TYPE_OPTIONS[1].priceTypeCode).toBe(44)  // market xtquant
    expect(PRICE_TYPE_OPTIONS[2].priceTypeCode).toBe(11)  // bidask 限价
  })
  it('DEFAULT_* 是 50 + last', () => {
    expect(DEFAULT_PCT).toBe(50)
    expect(DEFAULT_PRICE_TYPE).toBe('last')
  })
})


describe('roundToLot (整百股, 金融 floor)', () => {
  it('正数 floor: 123→100, 150→100, 1000→1000', () => {
    expect(roundToLot(123)).toBe(100)
    expect(roundToLot(150)).toBe(100)  // 150 不足 2 手, floor 到 100
    expect(roundToLot(1000)).toBe(1000)
  })
  it('250 → 200 (整百 floor)', () => {
    expect(roundToLot(250)).toBe(200)
    expect(roundToLot(251)).toBe(200)
  })
  it('0 和非数字 → 0', () => {
    expect(roundToLot(0)).toBe(0)
    expect(roundToLot(NaN)).toBe(0)
    expect(roundToLot(undefined)).toBe(0)
  })
  it('负数 floor: -150 → -200 (向 -∞ 方向)', () => {
    expect(roundToLot(-150)).toBe(-200)  // floor(-1.5) = -2
    expect(roundToLot(-123)).toBe(-200)  // floor(-1.23) = -2
  })
})


describe('calcBuyQty / calcQuickQty (按当前持仓百分比)', () => {
  it('1000 股 × 50% = 500', () => {
    expect(calcBuyQty({ vol: 1000 }, 50)).toBe(500)
  })
  it('1000 股 × 25% = 250 → roundToLot → 200', () => {
    expect(calcBuyQty({ vol: 1000 }, 25)).toBe(200)
  })
  it('100 股 × 100% = 100', () => {
    expect(calcBuyQty({ vol: 100 }, 100)).toBe(100)
  })
  it('0 持仓 → 0 (禁用分支)', () => {
    expect(calcBuyQty({ vol: 0 }, 50)).toBe(0)
    expect(calcBuyQty({}, 50)).toBe(0)  // 缺 vol
    expect(calcBuyQty(null, 50)).toBe(0)
  })
  it('calcSellQty 与 calcBuyQty 镜像', () => {
    expect(calcSellQty({ vol: 1000 }, 50)).toBe(500)
    expect(calcSellQty({ vol: 0 }, 50)).toBe(0)
  })
  it('calcQuickQty 接受 vol 直传 (行内快捷)', () => {
    expect(calcQuickQty(2000, 75)).toBe(1500)
    expect(calcQuickQty(2000, 0)).toBe(0)
  })
})


describe('resolvePrice (3 档价格, 不依赖行情)', () => {
  it('last → price=0 + 限价码 11 (broker 服务端解析)', () => {
    const r = resolvePrice('last', '600519.SH')
    expect(r.price).toBe(0)
    expect(r.priceTypeCode).toBe(11)
    expect(r.label).toBe('最新价')
  })
  it('market → price=0 + xtquant 码 44', () => {
    const r = resolvePrice('market', '600519.SH')
    expect(r.price).toBe(0)
    expect(r.priceTypeCode).toBe(44)
    expect(r.label).toBe('市价')
  })
  it('bidask → price=0 + 限价码 11 (broker 解析卖1买1)', () => {
    const r = resolvePrice('bidask', '600519.SH')
    expect(r.price).toBe(0)
    expect(r.priceTypeCode).toBe(11)
    expect(r.label).toBe('卖1买1')
  })
  it('未知 priceType → 默认限价 11', () => {
    const r = resolvePrice('xxx', '600519.SH')
    expect(r.priceTypeCode).toBe(11)
  })
})


describe('isBuyDisabled (0 持仓禁买, 用户拍板 A)', () => {
  it('vol > 0 → 不禁用', () => {
    expect(isBuyDisabled({ vol: 100 })).toBe(false)
  })
  it('vol === 0 → 禁用', () => {
    expect(isBuyDisabled({ vol: 0 })).toBe(true)
  })
  it('vol 缺失/无效 → 禁用', () => {
    expect(isBuyDisabled({})).toBe(true)
    expect(isBuyDisabled(null)).toBe(true)
  })
})


describe('validateQuick (提交校验)', () => {
  it('OK 情况 → null', () => {
    expect(validateQuick({ vol: 1000, stock_code: 'X' }, 500, 'buy')).toBe(null)
    expect(validateQuick({ vol: 1000, stock_code: 'X' }, 500, 'sell')).toBe(null)
  })
  it('0 持仓买 → 错误信息', () => {
    const err = validateQuick({ vol: 0, stock_code: 'X' }, 0, 'buy')
    expect(err).toMatch(/0 持仓/)
  })
  it('0 持仓卖 → 错误信息', () => {
    const err = validateQuick({ vol: 0, stock_code: 'X' }, 0, 'sell')
    expect(err).toMatch(/持仓数量为 0/)
  })
  it('qty=0 买 → 错误信息', () => {
    const err = validateQuick({ vol: 100, stock_code: 'X' }, 0, 'buy')
    expect(err).toMatch(/0 股/)
  })
  it('缺 stock_code → 无效行', () => {
    expect(validateQuick({ vol: 100 }, 100, 'buy')).toMatch(/无效/)
  })
})


describe('loadQuickDefaults / saveQuickDefaults (localStorage)', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('空 localStorage → 默认 50 + last', () => {
    expect(loadQuickDefaults()).toEqual({ pct: 50, priceType: 'last' })
  })
  it('写入后读取一致', () => {
    saveQuickDefaults(75, 'market')
    expect(loadQuickDefaults()).toEqual({ pct: 75, priceType: 'market' })
  })
  it('非法 pct 值 → 降级默认', () => {
    localStorage.setItem('t0.quickPct', '666')
    expect(loadQuickDefaults().pct).toBe(50)
  })
  it('非法 priceType → 降级默认', () => {
    localStorage.setItem('t0.quickPriceType', 'xxx')
    expect(loadQuickDefaults().priceType).toBe('last')
  })
})


describe('buildQuickOrder (端到端, 行内 [买 50%] 一键调用, 不依赖行情)', () => {
  const row = { stock_code: '600519.SH', vol: 1000 }

  it('1000 股 × 50% + last → qty=500, price=0, code=11', () => {
    const r = buildQuickOrder(row, 'buy', 50, 'last')
    expect(r.error).toBe(null)
    expect(r.qty).toBe(500)
    expect(r.price).toBe(0)
    expect(r.priceTypeCode).toBe(11)
  })

  it('1000 股 × 25% + last → qty=200 (整百截断 250→200)', () => {
    const r = buildQuickOrder(row, 'buy', 25, 'last')
    expect(r.qty).toBe(200)
  })

  it('0 持仓 buy → error (禁用分支)', () => {
    const r = buildQuickOrder({ stock_code: 'X', vol: 0 }, 'buy', 50, 'last')
    expect(r.error).toMatch(/0 持仓/)
  })

  it('0 持仓 sell → error', () => {
    const r = buildQuickOrder({ stock_code: 'X', vol: 0 }, 'sell', 50, 'last')
    expect(r.error).toMatch(/持仓数量为 0/)
  })

  it('market → price=0, code=44', () => {
    const r = buildQuickOrder(row, 'buy', 50, 'market')
    expect(r.price).toBe(0)
    expect(r.priceTypeCode).toBe(44)
  })

  it('bidask → price=0, code=11', () => {
    const r = buildQuickOrder(row, 'buy', 50, 'bidask')
    expect(r.price).toBe(0)
    expect(r.priceTypeCode).toBe(11)
  })
})
