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
  calcDayPnl,
  calcCommissionAndTax,
  calcFloatingPnl,
} from '@/lib/t0-calc'


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

describe('calcDayPnl', () => {
  const base = {
    vol: 1000, last_price: 11.0,
    last_vol: 1000, prev_close: 10.0,
    buy_amount: 0, sell_amount: 0, day_fee: 0,
  }

  it('无交易: 仅持仓随行情涨跌 (1000*11 − 1000*10 = 1000)', () => {
    expect(calcDayPnl(base)).toBeCloseTo(1000, 6)
  })

  it('有买卖+费用: (vol*last + sell) − (last_vol*prev + buy) − fee', () => {
    const p = calcDayPnl({
      ...base,
      vol: 500,          // 卖了 500 股
      sell_amount: 5500, // 卖 500@11
      buy_amount: 5000,  // 买了 500@10
      day_fee: 12.0,
    })
    // (500*11 + 5500) − (1000*10 + 5000) − 12 = 11000 − 15000 − 12 = -4012
    expect(p).toBeCloseTo(-4012, 6)
  })

  it('缺最新价 → null (UI 显示 —)', () => {
    expect(calcDayPnl({ ...base, last_price: null })).toBeNull()
  })
  it('缺昨收价 → null', () => {
    expect(calcDayPnl({ ...base, prev_close: null })).toBeNull()
  })
  it('非有限数防御: 任意字段 NaN → 按 0 处理, 不抛', () => {
    const p = calcDayPnl({ ...base, buy_amount: NaN, day_fee: NaN })
    expect(p).toBeCloseTo(1000, 6)
  })
  it('空参数 → null (无行情)', () => {
    expect(calcDayPnl()).toBeNull()
  })
})

describe('calcCommissionAndTax (floating-pnl-fee, 镜像 fees.py)', () => {
  // 默认费率 (对齐 sysconfig 当前规则: 万1免五、无印花税)
  const feeCfg = { commission_rate: 0.0001, min_commission: 0, stamp_tax_rate: 0 }

  it('买入: 只收佣金, 无印花税 (10000 × 万1 = 1.00)', () => {
    const r = calcCommissionAndTax(10000, feeCfg, ORDER_TYPE_BUY)
    expect(r.commission).toBeCloseTo(1.0, 6)
    expect(r.stamp_tax).toBe(0)
  })

  it('卖出: 佣金 + 印花税 (万5 印花税示例)', () => {
    const r = calcCommissionAndTax(10000, { ...feeCfg, stamp_tax_rate: 0.0005 }, ORDER_TYPE_SELL)
    // 佣金 1.00 + 印花税 5.00
    expect(r.commission).toBeCloseTo(1.0, 6)
    expect(r.stamp_tax).toBeCloseTo(5.0, 6)
  })

  it('佣金 round 2 (金额 × 费率后进位)', () => {
    // 0.33333 万元 × 万3 = 1.00 (0.99999 → round 1.00)
    const r = calcCommissionAndTax(33333, { ...feeCfg, commission_rate: 0.0003 }, ORDER_TYPE_BUY)
    expect(r.commission).toBeCloseTo(10.0, 6)
  })

  it('min_commission 兜底 (免五未开时 < 5 → 5)', () => {
    const r = calcCommissionAndTax(1000, { ...feeCfg, min_commission: 5 }, ORDER_TYPE_BUY)
    // 1000×万1=0.1 < 5 → 兜底 5
    expect(r.commission).toBe(5)
  })

  it('min_commission=0 (免五): 不兜底, 按实算', () => {
    const r = calcCommissionAndTax(1000, feeCfg, ORDER_TYPE_BUY)
    expect(r.commission).toBeCloseTo(0.1, 6)
  })

  it('amount <= 0 → 全 0', () => {
    expect(calcCommissionAndTax(0, feeCfg, ORDER_TYPE_SELL)).toEqual({ commission: 0, stamp_tax: 0 })
    expect(calcCommissionAndTax(-5, feeCfg, ORDER_TYPE_SELL)).toEqual({ commission: 0, stamp_tax: 0 })
  })

  it('空费率/空参 → 不抛, 全 0', () => {
    expect(calcCommissionAndTax(10000, {}, ORDER_TYPE_BUY)).toEqual({ commission: 0, stamp_tax: 0 })
    expect(calcCommissionAndTax(10000, undefined, ORDER_TYPE_BUY)).toEqual({ commission: 0, stamp_tax: 0 })
  })
})

describe('calcFloatingPnl (floating-pnl-fee, 对齐当日盈亏公式)', () => {
  const feeCfg = { commission_rate: 0.0001, min_commission: 0, stamp_tax_rate: 0 }

  it('无费率 → 裸价差 (10 → 12, 1000 股 = 2000)', () => {
    expect(calcFloatingPnl({ price: 12, cost: 10, vol: 1000, fee_cfg: null }))
      .toBeCloseTo(2000, 6)
  })

  it('扣费: (现价−成本)×量 − 买佣金 − 卖佣金 − 印花税', () => {
    // cost=10, price=12, vol=1000 → 毛利 2000
    // 买佣金 = round(10000×万1)=1.00; 卖佣金 = round(12000×万1)=1.20; 印花税=0
    // 净 = 2000 − 1.00 − 1.20 = 1997.80
    const r = calcFloatingPnl({ price: 12, cost: 10, vol: 1000, fee_cfg: feeCfg })
    expect(r).toBeCloseTo(1997.8, 6)
  })

  it('亏损也扣费 (毛利 < 0 仍减费用)', () => {
    // cost=12, price=10, vol=1000 → 毛利 −2000
    // 买佣金=round(12000×万1)=1.20; 卖佣金=round(10000×万1)=1.00
    // 净 = −2000 − 2.20 = −2002.20
    const r = calcFloatingPnl({ price: 10, cost: 12, vol: 1000, fee_cfg: feeCfg })
    expect(r).toBeCloseTo(-2002.2, 6)
  })

  it('印花税 (卖出) 计入: price×vol×stamp_tax_rate', () => {
    // stamp_tax_rate=0.001 (千一), price=12 → 12000×0.001 = 12.00
    const r = calcFloatingPnl({
      price: 12, cost: 10, vol: 1000,
      fee_cfg: { ...feeCfg, stamp_tax_rate: 0.001 },
    })
    // 2000 − 1.00 − 1.20 − 12.00 = 1985.80
    expect(r).toBeCloseTo(1985.8, 6)
  })

  it('缺行情 → null', () => {
    expect(calcFloatingPnl({ price: null, cost: 10, vol: 1000, fee_cfg: feeCfg })).toBeNull()
    expect(calcFloatingPnl({ price: undefined, cost: 10, vol: 1000, fee_cfg: feeCfg })).toBeNull()
  })

  it('vol=0 → 0 (空仓不扣费)', () => {
    expect(calcFloatingPnl({ price: 12, cost: 10, vol: 0, fee_cfg: feeCfg })).toBe(0)
  })

  it('空参 → null (无行情)', () => {
    expect(calcFloatingPnl()).toBeNull()
  })
})
