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
      // 无 amount → 0
    })
    expect(store.trades[0].amount).toBe(0)
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
})