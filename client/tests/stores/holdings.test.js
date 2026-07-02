/**
 * holdings.js applyTradePush 测试
 *
 * 覆盖：TradeOut 格式推送数据映射、缺失字段降级、幂等（重复 trade_id 不插入）
 *
 * 测试方法：直接 setActivePinia + useHoldingsStore，构造 trade row 触发 applyTradePush，
 *   断言 trades.value[0] 字段齐全。
 */
import { setActivePinia, createPinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// mock 依赖：避免 ws store / quote store / api 在测试环境真正加载
vi.mock('../../src/stores/ws', () => ({
  useWsStore: () => ({ connect: vi.fn(), disconnect: vi.fn() }),
}))
vi.mock('../../src/stores/quote', () => ({
  useQuoteStore: () => ({ update: vi.fn(), quotes: {} }),
}))
vi.mock('../../src/stores/asset', () => ({
  useAssetStore: () => ({ asset: { cash: 0, frozen_cash: 0, market_value: 0, total_asset: 0 } }),
}))
vi.mock('../../src/api', () => ({
  api: { get: vi.fn(), post: vi.fn() },
}))

import { useHoldingsStore } from '../../src/stores/holdings'

describe('holdings.applyTradePush', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('TradeOut 格式直接映射（push 重组包后字段已规范）', () => {
    const store = useHoldingsStore()
    const today = new Date()
    const todayStr = `${today.getFullYear()}${String(today.getMonth() + 1).padStart(2, '0')}${String(today.getDate()).padStart(2, '0')}`

    store.applyTradePush({
      trade_id: 'T001',
      order_id: 'broker-123',
      order_no: '10000001',
      trd_date: todayStr,
      stock_code: '600000.SH',
      order_type: '23',
      volume: 100,
      price: 10.5,
      amount: 1050,
      trade_time: '09:35:00',
      trade_type: 0,
    })

    expect(store.trades).toHaveLength(1)
    const t = store.trades[0]
    expect(t.trade_id).toBe('T001')
    expect(t.order_id).toBe('broker-123')
    expect(t.order_no).toBe('10000001')
    expect(t.trd_date).toBe(todayStr)
    expect(t.amount).toBe(1050)
    expect(t.trade_time).toBe('09:35:00')
    expect(t.trade_type).toBe(0)
  })

  it('amount/trd_date/order_no 缺失时降级默认值', () => {
    const store = useHoldingsStore()
    store.applyTradePush({
      trade_id: 'T002',
      stock_code: '600001.SH',
      order_type: '24',
      volume: 200,
      price: 5.0,
      // 无 amount → change system-delegation-price-fill-calc: 本地算 = price × volume = 1000
    })
    expect(store.trades[0].amount).toBe(1000)
    expect(store.trades[0].order_no).toBe('')
    // 无 trd_date → 今天
    expect(store.trades[0].trd_date).toBeDefined()
  })

  it('重复 trade_id 不重复插入', () => {
    const store = useHoldingsStore()
    const row = { trade_id: 'DUP', stock_code: '600002.SH', order_type: '23', volume: 10, price: 1.0 }
    store.applyTradePush(row)
    store.applyTradePush(row)  // 重复
    store.applyTradePush({ ...row, trade_id: 'DUP', volume: 20 })  // 同 trade_id 改 volume
    expect(store.trades).toHaveLength(1)
  })

  it('无 trade_id 静默丢弃（不崩）', () => {
    const store = useHoldingsStore()
    store.applyTradePush({ stock_code: '600003.SH', volume: 10 })
    expect(store.trades).toHaveLength(0)
  })

  // ──── change system-delegation-price-fill-calc: 增量累计 orders ────

  it('applyTradePush 增量累计 orders 中的对应委托（avg_price + status 重推断）', () => {
    const store = useHoldingsStore()
    const today = '20260702'
    // 模拟 bootstrap 已写入的原委托
    store.orders.push({
      order_no: '10000001',
      trd_date: today,
      stock_code: '600000.SH',
      order_type: '23',
      price: 10.0,
      volume: 100,
      traded_volume: 0,
      traded_amount: 0,
      avg_price: 0,
      cancelled_volume: 0,
      status: '49'  // 已报
    })

    store.applyTradePush({
      trade_id: 'T-INC',
      order_no: '10000001',
      trd_date: today,
      stock_code: '600000.SH',
      order_type: '23',
      price: 10.5,
      volume: 30,
      trade_time: '09:31:00',
      trade_type: 0,
    })

    // trade 入表, amount = 10.5 × 30 = 315 (本地算)
    const t = store.trades.find((x) => x.trade_id === 'T-INC')
    expect(t).toBeDefined()
    expect(t.amount).toBe(315)

    // 对应委托被累计
    const o = store.orders.find((x) => x.order_no === '10000001')
    expect(o.traded_volume).toBe(30)
    expect(o.traded_amount).toBe(315)
    expect(o.avg_price).toBe(10.5)
    expect(o.status).toBe('55') // 30/100 → broker 部成
  })

  it('applyTradePush 不采纳 broker.traded_amount（amount 永远本地算）', () => {
    const store = useHoldingsStore()
    store.applyTradePush({
      trade_id: 'T-DISC',
      stock_code: '600002.SH',
      order_type: '23',
      price: 12.5,
      volume: 100,
      // broker 推 amount=99999, 期望被丢弃
      amount: 99999,
    })
    const t = store.trades[0]
    expect(t.amount).toBe(1250) // 12.5 × 100
  })

  it('applyTradePush 多笔成交累计到 volume → status=56(broker 已成)', () => {
    const store = useHoldingsStore()
    const today = '20260702'
    store.orders.push({
      order_no: '10000002', trd_date: today,
      stock_code: '600010.SH', order_type: '23',
      price: 10, volume: 100,
      traded_volume: 0, traded_amount: 0, avg_price: 0, cancelled_volume: 0,
      status: '49'
    })

    // 3 笔各 30/30/40, 共 100
    store.applyTradePush({ trade_id: 'A', order_no: '10000002', trd_date: today, price: 10, volume: 30, stock_code: '600010.SH', order_type: '23' })
    store.applyTradePush({ trade_id: 'B', order_no: '10000002', trd_date: today, price: 10, volume: 30, stock_code: '600010.SH', order_type: '23' })
    store.applyTradePush({ trade_id: 'C', order_no: '10000002', trd_date: today, price: 10, volume: 40, stock_code: '600010.SH', order_type: '23' })

    const o = store.orders.find((x) => x.order_no === '10000002')
    expect(o.traded_volume).toBe(100)
    expect(o.traded_amount).toBe(1000)
    expect(o.avg_price).toBe(10)
    expect(o.status).toBe('56') // broker 已成
  })

  // ──── change system-delegation-price-fill-calc: applyOrderPush metaMerge ────

  it('applyOrderPush 普通 row 走 metaMerge: 累计字段保留 ref, 仅更新元数据', () => {
    const store = useHoldingsStore()
    const today = '20260702'
    store.orders.push({
      order_no: '10000003', trd_date: today,
      stock_code: '600020.SH', order_type: '23',
      price: 10, volume: 100,
      order_id: null,  // broker 还没回报
      traded_volume: 30, traded_amount: 300, avg_price: 10, cancelled_volume: 0,
      status: '50'
    })

    // broker 推 ord_cfm: 只填 broker 字段 + 试图覆盖累计
    store.applyOrderPush({
      order_no: '10000003', trd_date: today,
      order_id: 'BROKER-OID-X',
      order_time: '09:30:00',
      traded_volume: 999,    // broker 想覆盖, 不采纳
      traded_amount: 99999,  // broker 想覆盖, 不采纳
      status: '53'           // broker 推废单
    })

    const o = store.orders[0]
    expect(o.order_id).toBe('BROKER-OID-X')     // broker 字段采纳
    expect(o.order_time).toBe('09:30:00')
    expect(o.traded_volume).toBe(30)             // 累计保留 ref
    expect(o.traded_amount).toBe(300)
    expect(o.avg_price).toBe(10)
    // ref 累计 30/100 + broker_status=53 → rule 3: 0 < cum < vol → '53'(broker 部成部撤)
    expect(o.status).toBe('53')
  })

  it('applyOrderPush cancel-row 短路 + 反向抹平原委托 cancelled_volume', () => {
    const store = useHoldingsStore()
    const today = '20260702'
    // 原委托（已部分成交）
    store.orders.push({
      order_no: '10000004', trd_date: today,
      stock_code: '600030.SH', order_type: '23',
      price: 12.5, volume: 100,
      traded_volume: 30, traded_amount: 375, avg_price: 12.5,
      cancelled_volume: 0, status: '50'
    })

    // DELETE 端点 broadcast cancel-row (broker 54 已撤)
    store.applyOrderPush({
      order_no: '99999', trd_date: today,
      order_flag: 1, user_def: 'CANCEL:10000004',
      stock_code: '600030.SH', order_type: '23',
      price: 12.5, volume: 0, status: '54'
    })

    // cancel-row 自身入表
    const cancelRow = store.orders.find((o) => o.order_no === '99999')
    expect(cancelRow).toBeDefined()
    expect(cancelRow.order_flag).toBe(1)
    expect(cancelRow.status).toBe('54')

    // 原委托 cancelled_volume 被抹平到 100
    const orig = store.orders.find((o) => o.order_no === '10000004')
    expect(orig.cancelled_volume).toBe(100)
    // ref status='50' 非终态 + cancelled_volume=volume=100 → rule 2 → '54'(broker 已撤)
    expect(orig.status).toBe('54')
  })
})