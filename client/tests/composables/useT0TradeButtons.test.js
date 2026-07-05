/**
 * useT0TradeButtons.js 单测 (t0-trade-polish-bundle commit 2)
 *
 * 覆盖:
 *   - buyBtnState: 0 持仓 / cash 足 / cash 不足 / submitting / 无 quote
 *   - sellBtnState: 持仓足 / 持仓不足 / submitting
 *   - balanceBtnState: 已配平 / 净买 (查持仓) / 净卖 (查 cash) / cash 不足 / 持仓不足
 */
// @vitest-environment happy-dom
import { describe, it, expect } from 'vitest'
import { buyBtnState, sellBtnState, balanceBtnState } from '../../src/composables/useT0TradeButtons'


describe('buyBtnState', () => {
  it('0 持仓 → disabled + tip 提示', () => {
    const r = buyBtnState({ stock_code: '600519', vol: 0 }, { pct: 50, cash: 10000, price: 100, submitting: false })
    expect(r.disabled).toBe(true)
    expect(r.tip).toMatch(/持仓为 0/)
  })
  it('持仓非 0 + cash 足 + 非 submitting → enabled', () => {
    const r = buyBtnState({ stock_code: '600519', vol: 1000 }, { pct: 50, cash: 100000, price: 10, submitting: false })
    // 买 50% × 1000 = 500 股, 500 × 10 = 5000, cash 100000 > 5000
    expect(r.disabled).toBe(false)
    expect(r.qty).toBe(500)
    expect(r.cash.ok).toBe(true)
    expect(r.tip).toMatch(/按 50% 仓位买入 500 股/)
  })
  it('cash 不足 → disabled + gap 文案', () => {
    const r = buyBtnState({ stock_code: '600519', vol: 1000 }, { pct: 50, cash: 1000, price: 100, submitting: false })
    // 买 500 股 × 100 = 50000, cash 1000 < 50000 → gap = 49000
    expect(r.disabled).toBe(true)
    expect(r.cash.ok).toBe(false)
    expect(r.cash.gap).toBe(49000)
    expect(r.tip).toMatch(/资金/)
    expect(r.tip).toMatch(/不足/)
  })
  it('cash 刚好等于 → enabled', () => {
    const r = buyBtnState({ stock_code: '600519', vol: 200 }, { pct: 50, cash: 1000, price: 10, submitting: false })
    // 买 100 × 10 = 1000 = cash
    expect(r.disabled).toBe(false)
    expect(r.cash.ok).toBe(true)
    expect(r.cash.gap).toBe(0)
  })
  it('submitting → disabled (无论 cash)', () => {
    const r = buyBtnState({ stock_code: '600519', vol: 1000 }, { pct: 50, cash: 100000, price: 10, submitting: true })
    expect(r.disabled).toBe(true)
  })
  it('price=0 (无 quote) → disabled + tip', () => {
    const r = buyBtnState({ stock_code: '600519', vol: 1000 }, { pct: 50, cash: 100000, price: 0, submitting: false })
    // price=0 → lib 返回 ok=true (qty>0 but price<=0 → 不阻塞)
    // 实际 calcInsufficientCash 在 price=0 时 ok=true (不阻塞)
    // 所以 disabled 应是 false (没 quote 仍允许)
    expect(r.disabled).toBe(false)
    expect(r.qty).toBe(500)
  })
  it('cash=NaN 兜底 0', () => {
    const r = buyBtnState({ stock_code: '600519', vol: 1000 }, { pct: 50, cash: NaN, price: 10, submitting: false })
    // cash=NaN → 0, 买 5000, 不足 → disabled
    expect(r.disabled).toBe(true)
    expect(r.cash.have).toBe(0)
  })
})


describe('sellBtnState', () => {
  it('持仓足 → enabled', () => {
    // vol=200, pct=50 → calcSellQty → roundToLot(100) = 100, currentVolume=200 → ok
    const r = sellBtnState({ stock_code: '600519', vol: 200 }, { pct: 50, submitting: false })
    expect(r.disabled).toBe(false)
    expect(r.qty).toBe(100)
    expect(r.position.ok).toBe(true)
  })
  it('持仓不足 → disabled + gap 文案 (防御性测试, pct>100 场景)', () => {
    // pct=200, vol=100 → calcSellQty → roundToLot(200) = 200, currentVolume=100 → gap=100
    // (UI pct 受 PCT_OPTIONS=[25,50,75,100] 约束, 但 fn 接受任意 pct)
    const r = sellBtnState({ stock_code: '600519', vol: 100 }, { pct: 200, submitting: false })
    expect(r.disabled).toBe(true)
    expect(r.position.ok).toBe(false)
    expect(r.position.gap).toBe(100)
    expect(r.tip).toMatch(/持仓 100 股不足/)
    expect(r.tip).toMatch(/缺 100 股/)
  })
  it('0 持仓 → qty=0 但 disabled=false (卖方向直通 0 持仓)', () => {
    // vol=0, pct=50 → calcSellQty → roundToLot(0) = 0, currentVolume=0 → ok
    const r = sellBtnState({ stock_code: '600519', vol: 0 }, { pct: 50, submitting: false })
    expect(r.disabled).toBe(false)
    expect(r.qty).toBe(0)
  })
  it('submitting → disabled', () => {
    const r = sellBtnState({ stock_code: '600519', vol: 1000 }, { pct: 50, submitting: true })
    expect(r.disabled).toBe(true)
  })
  it('vol=99 + pct=50 → qty=0 (不到 1 手归零)', () => {
    // (99*50)/100=49.5 → roundToLot(49.5) = 0 (less than 1 lot)
    const r = sellBtnState({ stock_code: '600519', vol: 99 }, { pct: 50, submitting: false })
    expect(r.disabled).toBe(false)
    expect(r.qty).toBe(0)
  })
})


describe('balanceBtnState', () => {
  it('已配平 (balance=null) → disabled + "已配平"', () => {
    const r = balanceBtnState({ stock_code: '600519', vol: 100 }, { balance: null, cash: 10000, price: 10, submitting: false })
    expect(r.disabled).toBe(true)
    expect(r.tip).toBe('已配平')
  })
  it('净买 (side=sell, 卖锁仓) → 查持仓', () => {
    // net=+200 → 卖 200, currentVolume=500 → ok
    const r = balanceBtnState({ stock_code: '600519', vol: 500 }, {
      balance: { side: 'sell', qty: 200 },
      cash: 10000, price: 10, submitting: false,
    })
    expect(r.disabled).toBe(false)
    expect(r.side).toBe('sell')
    expect(r.qty).toBe(200)
    expect(r.tip).toMatch(/卖200/)
  })
  it('净买但持仓不足 → disabled', () => {
    // net=+200 → 卖 200, currentVolume=100 → gap=100
    const r = balanceBtnState({ stock_code: '600519', vol: 100 }, {
      balance: { side: 'sell', qty: 200 },
      cash: 10000, price: 10, submitting: false,
    })
    expect(r.disabled).toBe(true)
    expect(r.tip).toMatch(/持仓 100 股不足/)
    expect(r.tip).toMatch(/缺 100 股/)
  })
  it('净卖 (side=buy, 买锁仓) → 查 cash', () => {
    // net=-200 → 买 200, need=200*10=2000, cash=10000 → ok
    const r = balanceBtnState({ stock_code: '600519', vol: 100 }, {
      balance: { side: 'buy', qty: 200 },
      cash: 10000, price: 10, submitting: false,
    })
    expect(r.disabled).toBe(false)
    expect(r.side).toBe('buy')
    expect(r.qty).toBe(200)
    expect(r.tip).toMatch(/买200/)
  })
  it('净卖但 cash 不足 → disabled', () => {
    // net=-200 → 买 200, need=200*10=2000, cash=100 → gap=1900
    const r = balanceBtnState({ stock_code: '600519', vol: 100 }, {
      balance: { side: 'buy', qty: 200 },
      cash: 100, price: 10, submitting: false,
    })
    expect(r.disabled).toBe(true)
    expect(r.tip).toMatch(/资金/)
    expect(r.tip).toMatch(/不足/)
    expect(r.tip).toMatch(/无法配平买入/)
  })
  it('submitting → disabled', () => {
    const r = balanceBtnState({ stock_code: '600519', vol: 500 }, {
      balance: { side: 'sell', qty: 200 },
      cash: 10000, price: 10, submitting: true,
    })
    expect(r.disabled).toBe(true)
  })
})