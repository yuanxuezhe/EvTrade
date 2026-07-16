/**
 * t0-calc.js 纯函数单测 (t0-trade-polish-bundle)
 *
 * 覆盖边界:
 *   - roundToLot: 0 / NaN / 负 / 99(<lot) / 跨手 / 非默认 lot
 *   - calcBalanceQty: 已平仓 / 净买 / 净卖 / NaN vol
 *   - calcInsufficientCash: buy 资金足/不足/卖方向直通/qty=0/qty=NaN
 *   - calcInsufficientPosition: sell 持仓足/不足/买方向直通/qty=0
 *   - resolvePriceTypeCode: 3 已知值 + 未知 string 兜底
 */
// @vitest-environment happy-dom
import { describe, it, expect } from 'vitest'
import {
  DEFAULT_LOT_SIZE,
  ORDER_TYPE_BUY,
  ORDER_TYPE_SELL,
  roundToLot,
  calcBalanceQty,
  calcInsufficientCash,
  calcInsufficientPosition,
  resolvePriceTypeCode,
  // v54 quick-t0-revamp 新增
  calcT0Pnl,
  calcExposure,
  calcInitialQuota,
  calcT0ReturnRate,
  resolveBalancePrice,
} from '../../src/lib/t0-calc'


describe('constants', () => {
  it('DEFAULT_LOT_SIZE = 100', () => {
    expect(DEFAULT_LOT_SIZE).toBe(100)
  })
  it('broker order type codes', () => {
    expect(ORDER_TYPE_BUY).toBe('23')
    expect(ORDER_TYPE_SELL).toBe('24')
  })
})


describe('roundToLot', () => {
  it('整手 floor 向 -∞', () => {
    expect(roundToLot(250)).toBe(200)
    expect(roundToLot(150)).toBe(100)
    expect(roundToLot(-150)).toBe(-200)
    expect(roundToLot(199)).toBe(100)
  })
  it('整手值不变', () => {
    expect(roundToLot(100)).toBe(100)
    expect(roundToLot(500)).toBe(500)
    expect(roundToLot(-500)).toBe(-500)
  })
  it('小于 1 手归零', () => {
    expect(roundToLot(99)).toBe(0)
    expect(roundToLot(50)).toBe(0)
    expect(roundToLot(-50)).toBe(0)
    expect(roundToLot(1)).toBe(0)
  })
  it('0 / NaN / null 返 0', () => {
    expect(roundToLot(0)).toBe(0)
    expect(roundToLot(NaN)).toBe(0)
    expect(roundToLot(null)).toBe(0)
    expect(roundToLot(undefined)).toBe(0)
    expect(roundToLot('abc')).toBe(0)
  })
  it('自定义 lotSize', () => {
    expect(roundToLot(150, 50)).toBe(150)
    expect(roundToLot(149, 50)).toBe(100)
    expect(roundToLot(550, 200)).toBe(400)
  })
})


describe('calcBalanceQty', () => {
  // 公式: need = vol + (todayBuy - todaySell)
  //   need > 0 → 买 (qty=roundToLot(need))
  //   need < 0 → 卖 (qty=roundToLot(|need|))
  //   need = 0 → 已平仓
  it('已平仓 (need = 0)', () => {
    // 昨仓 100, 今全卖 100, 今买 0 → need = 100 + (0 - 100) = 0 → 平仓
    const r = calcBalanceQty({ vol: 100, todayBuy: 0, todaySell: 100 })
    expect(r.qty).toBe(0)
    expect(r.side).toBeNull()
    expect(r.error).toMatch(/平仓/)
  })
  it('净买入 (need > 0) → 需买', () => {
    // need = 100 + (200 - 100) = 200 → 买 200
    const r = calcBalanceQty({ vol: 100, todayBuy: 200, todaySell: 100 })
    expect(r.qty).toBe(200)
    expect(r.side).toBe('buy')
    expect(r.error).toBeNull()
  })
  it('净卖出 (need < 0) → 需卖', () => {
    // need = 100 + (100 - 300) = -100 → 卖 100
    const r = calcBalanceQty({ vol: 100, todayBuy: 100, todaySell: 300 })
    expect(r.qty).toBe(100)
    expect(r.side).toBe('sell')
    expect(r.error).toBeNull()
  })
  it('NaN vol 兜底 0', () => {
    // Number(NaN)||0 → 0; net=100-0=100; need=0+100=100 → 买 100
    const r = calcBalanceQty({ vol: NaN, todayBuy: 100, todaySell: 0 })
    expect(r.qty).toBe(100)
    expect(r.side).toBe('buy')
  })
  it('缺失参数兜底', () => {
    const r = calcBalanceQty({})  // all defaults → need = 0 → 平仓
    expect(r.error).toMatch(/平仓/)
  })
  it('配平量整百取整', () => {
    // need = 250 + 0 = 250 → roundToLot(250) = 200
    const r = calcBalanceQty({ vol: 250, todayBuy: 0, todaySell: 0 })
    expect(r.qty).toBe(200)
    expect(r.side).toBe('buy')
  })
})


describe('calcInsufficientCash', () => {
  it('buy 资金足 → ok', () => {
    const r = calcInsufficientCash({ side: 'buy', qty: 100, price: 10, cash: 2000 })
    expect(r.ok).toBe(true)
    expect(r.need).toBe(1000)
    expect(r.have).toBe(2000)
    expect(r.gap).toBe(0)
  })
  it('buy 资金不足 → not ok + gap', () => {
    const r = calcInsufficientCash({ side: 'buy', qty: 100, price: 10, cash: 500 })
    expect(r.ok).toBe(false)
    expect(r.need).toBe(1000)
    expect(r.have).toBe(500)
    expect(r.gap).toBe(500)
  })
  it('buy 资金刚好等于 → ok', () => {
    const r = calcInsufficientCash({ side: 'buy', qty: 100, price: 10, cash: 1000 })
    expect(r.ok).toBe(true)
    expect(r.gap).toBe(0)
  })
  it('sell 方向不查资金 → ok 直通', () => {
    const r = calcInsufficientCash({ side: 'sell', qty: 100, price: 10, cash: 0 })
    expect(r.ok).toBe(true)
    expect(r.need).toBe(0)
    expect(r.have).toBe(0)
  })
  it('buy qty=0 不阻塞', () => {
    const r = calcInsufficientCash({ side: 'buy', qty: 0, price: 10, cash: 0 })
    expect(r.ok).toBe(true)
  })
  it('buy qty=NaN 兜底 ok', () => {
    const r = calcInsufficientCash({ side: 'buy', qty: NaN, price: 10, cash: 0 })
    expect(r.ok).toBe(true)
  })
  it('cash=NaN 兜底 0', () => {
    const r = calcInsufficientCash({ side: 'buy', qty: 100, price: 10, cash: NaN })
    expect(r.ok).toBe(false)
    expect(r.have).toBe(0)
    expect(r.gap).toBe(1000)
  })
})


describe('calcInsufficientPosition', () => {
  it('sell 持仓足 → ok', () => {
    const r = calcInsufficientPosition({ side: 'sell', qty: 100, currentVolume: 500 })
    expect(r.ok).toBe(true)
    expect(r.need).toBe(100)
    expect(r.have).toBe(500)
    expect(r.gap).toBe(0)
  })
  it('sell 持仓不足 → not ok + gap', () => {
    const r = calcInsufficientPosition({ side: 'sell', qty: 500, currentVolume: 100 })
    expect(r.ok).toBe(false)
    expect(r.need).toBe(500)
    expect(r.have).toBe(100)
    expect(r.gap).toBe(400)
  })
  it('sell 持仓刚好等于 → ok', () => {
    const r = calcInsufficientPosition({ side: 'sell', qty: 100, currentVolume: 100 })
    expect(r.ok).toBe(true)
    expect(r.gap).toBe(0)
  })
  it('buy 方向不查持仓 → ok 直通', () => {
    const r = calcInsufficientPosition({ side: 'buy', qty: 100, currentVolume: 0 })
    expect(r.ok).toBe(true)
  })
  it('sell qty=0 不阻塞', () => {
    const r = calcInsufficientPosition({ side: 'sell', qty: 0, currentVolume: 100 })
    expect(r.ok).toBe(true)
  })
  it('currentVolume=NaN 兜底 0', () => {
    const r = calcInsufficientPosition({ side: 'sell', qty: 100, currentVolume: NaN })
    expect(r.ok).toBe(false)
    expect(r.have).toBe(0)
    expect(r.gap).toBe(100)
  })
})


describe('resolvePriceTypeCode', () => {
  it('last → 11', () => {
    expect(resolvePriceTypeCode('last')).toBe(11)
  })
  it('market → 44', () => {
    expect(resolvePriceTypeCode('market')).toBe(44)
  })
  it('bidask → 11 (现状)', () => {
    expect(resolvePriceTypeCode('bidask')).toBe(11)
  })
  it('未知字符串兜底 11', () => {
    expect(resolvePriceTypeCode('foo')).toBe(11)
    expect(resolvePriceTypeCode('')).toBe(11)
    expect(resolvePriceTypeCode(undefined)).toBe(11)
    expect(resolvePriceTypeCode(null)).toBe(11)
  })
})


// ============== v54 quick-t0-revamp: 新增 5 函数单测 ==============

describe('calcT0Pnl (做T盈亏)', () => {
  it('正常: 卖 1500 - 买 1000 = +500', () => {
    expect(calcT0Pnl({ today_buy_amount: 1000, today_sell_amount: 1500 })).toBe(500)
  })
  it('正常: 卖 800 - 买 1200 = -400', () => {
    expect(calcT0Pnl({ today_buy_amount: 1200, today_sell_amount: 800 })).toBe(-400)
  })
  it('无成交: 0', () => {
    expect(calcT0Pnl({})).toBe(0)
    expect(calcT0Pnl({ today_buy_amount: 0, today_sell_amount: 0 })).toBe(0)
  })
  it('null/undefined/非对象: 0', () => {
    expect(calcT0Pnl(null)).toBe(0)
    expect(calcT0Pnl(undefined)).toBe(0)
    expect(calcT0Pnl('foo')).toBe(0)
  })
  it('NaN/字符串: 0', () => {
    expect(calcT0Pnl({ today_buy_amount: 'foo', today_sell_amount: NaN })).toBe(0)
  })
  it('边界: 大数', () => {
    expect(calcT0Pnl({ today_buy_amount: 1e9, today_sell_amount: 1e9 + 1234 })).toBe(1234)
  })
})


describe('calcExposure (敞口)', () => {
  it('净买: 期初 1000 + 买 300 - 卖 0 = +1300 多头敞口', () => {
    expect(calcExposure(
      { last_vol: 1000 },
      { today_buy_volume: 300, today_sell_volume: 0 }
    )).toBe(1300)
  })
  it('净卖: 期初 1000 + 买 0 - 卖 1200 = -200 空头敞口', () => {
    expect(calcExposure(
      { last_vol: 1000 },
      { today_buy_volume: 0, today_sell_volume: 1200 }
    )).toBe(-200)
  })
  it('已配平: 买 = 卖 = 期初', () => {
    expect(calcExposure(
      { last_vol: 1000 },
      { today_buy_volume: 500, today_sell_volume: 500 }
    )).toBe(1000)  // 配平 = 还持有 1000 (因为买 500 卖 500, 持仓回到 1000)
  })
  it('缺字段: 0', () => {
    expect(calcExposure({}, {})).toBe(0)
    expect(calcExposure(null, null)).toBe(0)
    expect(calcExposure(undefined, undefined)).toBe(0)
  })
  it('NaN → 0', () => {
    expect(calcExposure({ last_vol: NaN }, { today_buy_volume: 100 })).toBe(100)
    expect(calcExposure({ last_vol: 1000 }, { today_buy_volume: NaN })).toBe(1000)
  })
  it('典型 T0 场景: 期初 1000, 买 300, 卖 100 → +1200 (持仓视角)', () => {
    expect(calcExposure(
      { last_vol: 1000 },
      { today_buy_volume: 300, today_sell_volume: 100 }
    )).toBe(1200)
  })
})


describe('calcInitialQuota (期初配额)', () => {
  it('期初 1000, 买 300, 卖 200 → 可买 700 / 可卖 800', () => {
    expect(calcInitialQuota(
      { last_vol: 1000 },
      { today_buy_volume: 300, today_sell_volume: 200 }
    )).toEqual({ maxBuyable: 700, maxSellable: 800 })
  })
  it('无成交: 可买 = 可卖 = 期初', () => {
    expect(calcInitialQuota(
      { last_vol: 1000 },
      {}
    )).toEqual({ maxBuyable: 1000, maxSellable: 1000 })
  })
  it('已超额: max(0, last - 已成交)', () => {
    // 买 1500 > 期初 1000 → maxBuyable = 0
    expect(calcInitialQuota(
      { last_vol: 1000 },
      { today_buy_volume: 1500 }
    )).toEqual({ maxBuyable: 0, maxSellable: 1000 })
    // 卖 1500 > 期初 1000 → maxSellable = 0
    expect(calcInitialQuota(
      { last_vol: 1000 },
      { today_sell_volume: 1500 }
    )).toEqual({ maxBuyable: 1000, maxSellable: 0 })
  })
  it('缺字段: 0', () => {
    expect(calcInitialQuota({}, {})).toEqual({ maxBuyable: 0, maxSellable: 0 })
    expect(calcInitialQuota(null, null)).toEqual({ maxBuyable: 0, maxSellable: 0 })
  })
  it('典型 T0 配平后: 期初 1000, 买 300, 卖 300 → 还可买 700 / 还可卖 700', () => {
    expect(calcInitialQuota(
      { last_vol: 1000 },
      { today_buy_volume: 300, today_sell_volume: 300 }
    )).toEqual({ maxBuyable: 700, maxSellable: 700 })
  })
})


describe('calcT0ReturnRate (做T收益率)', () => {
  it('典型: 期初 1000 @ 10, 卖 1500 - 买 1000 = +500 / 10000 = 0.05 (5%)', () => {
    expect(calcT0ReturnRate(
      { last_vol: 1000, cost_price: 10 },
      { today_buy_amount: 1000, today_sell_amount: 1500 }
    )).toBe(0.05)
  })
  it('亏损: 卖 800 - 买 1200 = -400 / 10000 = -0.04 (-4%)', () => {
    expect(calcT0ReturnRate(
      { last_vol: 1000, cost_price: 10 },
      { today_buy_amount: 1200, today_sell_amount: 800 }
    )).toBe(-0.04)
  })
  it('边界: 期初 0 → 0', () => {
    expect(calcT0ReturnRate(
      { last_vol: 0, cost_price: 10 },
      { today_buy_amount: 1000, today_sell_amount: 1500 }
    )).toBe(0)
  })
  it('边界: 成本 0 → 0', () => {
    expect(calcT0ReturnRate(
      { last_vol: 1000, cost_price: 0 },
      { today_buy_amount: 1000, today_sell_amount: 1500 }
    )).toBe(0)
  })
  it('无成交: 0', () => {
    expect(calcT0ReturnRate(
      { last_vol: 1000, cost_price: 10 },
      {}
    )).toBe(0)
  })
  it('小数股: 期初 100 @ 0.5, 卖 60 - 买 50 = +10 / 50 = 0.2 (20%)', () => {
    expect(calcT0ReturnRate(
      { last_vol: 100, cost_price: 0.5 },
      { today_buy_amount: 50, today_sell_amount: 60 }
    )).toBeCloseTo(0.2, 10)
  })
  it('缺字段: 0', () => {
    expect(calcT0ReturnRate({}, {})).toBe(0)
    expect(calcT0ReturnRate(null, null)).toBe(0)
  })
})


describe('resolveBalancePrice (配平对手盘价)', () => {
  it('买敞口 → ask1 (卖1价)', () => {
    expect(resolveBalancePrice(
      { stock_code: '000001.SZ' },
      'buy',
      { last_price: 10, ask_prices: [11.5, 11.6], bid_prices: [10.5, 10.4] }
    )).toEqual({ price: 11.5, fallback: false })
  })
  it('卖敞口 → bid1 (买1价)', () => {
    expect(resolveBalancePrice(
      { stock_code: '000001.SZ' },
      'sell',
      { last_price: 10, ask_prices: [11.5, 11.6], bid_prices: [10.5, 10.4] }
    )).toEqual({ price: 10.5, fallback: false })
  })
  it('买敞口: ask1 无效 → fallback 最新价', () => {
    expect(resolveBalancePrice(
      { stock_code: '000001.SZ' },
      'buy',
      { last_price: 10, ask_prices: [0, null, undefined] }
    )).toEqual({ price: 10, fallback: true })
  })
  it('卖敞口: bid1 无效 → fallback 最新价', () => {
    expect(resolveBalancePrice(
      { stock_code: '000001.SZ' },
      'sell',
      { last_price: 10, bid_prices: [] }
    )).toEqual({ price: 10, fallback: true })
  })
  it('无任何价: price=0 fallback=true', () => {
    expect(resolveBalancePrice(
      { stock_code: '000001.SZ' },
      'buy',
      { last_price: 0 }
    )).toEqual({ price: 0, fallback: true })
    expect(resolveBalancePrice(
      { stock_code: '000001.SZ' },
      'sell',
      null
    )).toEqual({ price: 0, fallback: true })
  })
  it('quote 为 undefined: 兜底 0', () => {
    expect(resolveBalancePrice(
      { stock_code: '000001.SZ' },
      'buy',
      undefined
    )).toEqual({ price: 0, fallback: true })
  })
  it('未知 side: 返 last_price 不 fallback', () => {
    expect(resolveBalancePrice(
      { stock_code: '000001.SZ' },
      'unknown',
      { last_price: 10 }
    )).toEqual({ price: 10, fallback: false })
  })
  it('边界: ask_prices[0] = NaN → fallback 最新价', () => {
    expect(resolveBalancePrice(
      { stock_code: '000001.SZ' },
      'buy',
      { last_price: 10, ask_prices: [NaN, 11.5] }
    )).toEqual({ price: 10, fallback: true })
  })
})
