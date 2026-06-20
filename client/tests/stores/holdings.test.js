/**
 * holdings.js applyTradePush 测试（M-003 / f6beffc）
 *
 * 覆盖 v7 改动：applyTradePush 补全 trd_date / order_no / amount 字段
 *   - trd_date 用于跨日分组
 *   - order_no 关联委托（兼容 broker 透传的 remark 字段）
 *   - amount = volume × price（持仓做T敞口/累计收益计算需要）
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

  it('补全 trd_date / order_no / amount 字段（M-003）', () => {
    const store = useHoldingsStore()
    const today = new Date()
    const todayStr = `${today.getFullYear()}${String(today.getMonth() + 1).padStart(2, '0')}${String(today.getDate()).padStart(2, '0')}`

    store.applyTradePush({
      trade_id: 'T001',
      order_id: 'broker-123',
      stock_code: '600000.SH',
      order_type: '23',  // 买
      volume: 100,
      price: 10.5,
      // broker 透传 remark 作为本地 order_no 兼容
      remark: 'LOCAL-001',
      trade_time: '09:35:00',
    })

    expect(store.trades).toHaveLength(1)
    const t = store.trades[0]
    expect(t.trade_id).toBe('T001')
    expect(t.order_id).toBe('broker-123')
    // f6beffc 关键改动：3 个字段都被补全
    expect(t.order_no).toBe('LOCAL-001')         // 从 remark 兼容
    expect(t.trd_date).toBe(todayStr)              // 今日日期
    expect(t.amount).toBe(100 * 10.5)              // 1050
    expect(t.trade_time).toBe('09:35:00')
  })

  it('amount 字段缺失时按 volume × price 计算', () => {
    const store = useHoldingsStore()
    store.applyTradePush({
      trade_id: 'T002',
      stock_code: '600001.SH',
      order_type: '24',  // 卖
      volume: 200,
      price: 5.0,
    })
    expect(store.trades[0].amount).toBe(1000)
    // 没 remark → order_no 应为空字符串
    expect(store.trades[0].order_no).toBe('')
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