/**
 * test_holdings_idb.js — IDB 持久化层单元测试（v13 optimize-push-data-flow: 复合 PK）
 *
 * 覆盖（对应 intraday-orders-trades-cache/spec.md）:
 *   - saveOrder / saveTrade → loadOrdersForDate / loadTradesForDate 回路
 *   - 跨日：loadOrdersForDate('20260703') 不影响 loadOrdersForDate('20260704')
 *   - 跨日清理：clearDate('20260703') 删当日所有复合 key，不影响其他日期
 *   - 复合 key 维度：同日多笔订单可独立存取, 不串
 *   - push 双写：fire-and-forget，不阻塞 caller
 *   - IDB 不可用 → init 抛错被 catch，save 不抛
 *
 * 实现: 用 vi.mock 替换 utils/idb 的 openDB/idbGet/idbPut/idbDelete/idbGetAllKeys,
 * 注入 Map 模拟 IDB 数据（per-store 独立 Map<compositeKey, value>）
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

// 共享存储（mock 内部使用） - 通过 module-level 刷新
let _idbStore = new Map()  // storeName -> Map<compositeKey, value>

vi.mock('../../src/utils/idb', () => ({
  openDB: vi.fn(async (_name, _version, _stores, onUpgrade) => {
    // 模拟 onUpgrade 回调（清旧 store, 由 storeNames 重建）
    if (typeof onUpgrade === 'function') {
      const fakeDb = {
        objectStoreNames: {
          contains: (name) => _idbStore.has(name),
        },
        deleteObjectStore: (name) => { _idbStore.delete(name) },
        createObjectStore: (name) => { if (!_idbStore.has(name)) _idbStore.set(name, new Map()) },
      }
      onUpgrade(fakeDb, 1, 2)
    }
    return { __fakeDb: true }
  }),
  idbGet: vi.fn(async (_db, store, key) => {
    const m = _idbStore.get(store)
    if (!m) return null
    return m.has(key) ? m.get(key) : null
  }),
  idbPut: vi.fn(async (_db, store, key, value) => {
    if (!_idbStore.has(store)) _idbStore.set(store, new Map())
    _idbStore.get(store).set(key, value)
  }),
  idbDelete: vi.fn(async (_db, store, key) => {
    const m = _idbStore.get(store)
    if (m) m.delete(key)
  }),
  idbClear: vi.fn(async (_db, store) => {
    if (_idbStore.has(store)) _idbStore.get(store).clear()
  }),
  idbGetAllKeys: vi.fn(async (_db, store) => {
    const m = _idbStore.get(store)
    return m ? Array.from(m.keys()) : []
  }),
}))

const idb = await import('../../src/stores/holdings_idb')


beforeEach(async () => {
  _idbStore = new Map()
  idb._resetForTests()
  vi.clearAllMocks()
})


describe('holdings_idb — 复合 PK 读写回路', () => {
  it('saveOrder → loadOrdersForDate 读回原值 (单笔)', async () => {
    await idb.initIDB()
    idb.saveOrder({ trd_date: '20260704', order_no: '10000001', status: '50', price: 12.5 })
    await new Promise((r) => setTimeout(r, 0))
    const loaded = await idb.loadOrdersForDate('20260704')
    expect(loaded).toHaveLength(1)
    expect(loaded[0].order_no).toBe('10000001')
    expect(loaded[0].price).toBe(12.5)
  })

  it('saveTrade → loadTradesForDate 读回原值 (单笔)', async () => {
    await idb.initIDB()
    idb.saveTrade({ trd_date: '20260704', order_no: '10000001', trade_id: 'T001', volume: 100, price: 5.0 })
    await new Promise((r) => setTimeout(r, 0))
    const loaded = await idb.loadTradesForDate('20260704')
    expect(loaded).toHaveLength(1)
    expect(loaded[0].trade_id).toBe('T001')
    expect(loaded[0].volume).toBe(100)
  })

  it('同日多笔 orders 复合 key 不串', async () => {
    await idb.initIDB()
    idb.saveOrder({ trd_date: '20260704', order_no: '10000001', price: 12.5 })
    idb.saveOrder({ trd_date: '20260704', order_no: '10000002', price: 9.0 })
    idb.saveOrder({ trd_date: '20260704', order_no: '10000003', price: 7.0 })
    await new Promise((r) => setTimeout(r, 0))
    const loaded = await idb.loadOrdersForDate('20260704')
    expect(loaded).toHaveLength(3)
    const noList = loaded.map(o => o.order_no).sort()
    expect(noList).toEqual(['10000001', '10000002', '10000003'])
  })

  it('同日多笔 trades 同 order_no 不同 trade_id 不串', async () => {
    await idb.initIDB()
    idb.saveTrade({ trd_date: '20260704', order_no: '10000001', trade_id: 'T001', volume: 100 })
    idb.saveTrade({ trd_date: '20260704', order_no: '10000001', trade_id: 'T002', volume: 200 })
    idb.saveTrade({ trd_date: '20260704', order_no: '10000002', trade_id: 'T003', volume: 300 })
    await new Promise((r) => setTimeout(r, 0))
    const loaded = await idb.loadTradesForDate('20260704')
    expect(loaded).toHaveLength(3)
    const tidList = loaded.map(t => t.trade_id).sort()
    expect(tidList).toEqual(['T001', 'T002', 'T003'])
  })

  it('loadOrdersForDate miss → null', async () => {
    await idb.initIDB()
    const loaded = await idb.loadOrdersForDate('20991231')
    expect(loaded).toBeNull()
  })

  it('loadOrdersForDate(空字符串) → null', async () => {
    await idb.initIDB()
    const loaded = await idb.loadOrdersForDate('')
    expect(loaded).toBeNull()
  })

  it('saveOrder(null) 不抛错', async () => {
    await idb.initIDB()
    expect(() => idb.saveOrder(null)).not.toThrow()
    expect(() => idb.saveOrder({})).not.toThrow()  // 缺 trd_date/order_no 也 noop
    expect(() => idb.saveOrder({ trd_date: '20260704' })).not.toThrow()  // 缺 order_no
  })

  it('saveOrder 深拷贝隔离（修改原对象不影响 IDB）', async () => {
    await idb.initIDB()
    const order = { trd_date: '20260704', order_no: '10000001', price: 10 }
    idb.saveOrder(order)
    await new Promise((r) => setTimeout(r, 0))
    order.price = 999
    const loaded = await idb.loadOrdersForDate('20260704')
    expect(loaded[0].price).toBe(10)
  })

  it('saveOrder 同 order_no 二次写覆盖（O(1) idbPut）', async () => {
    await idb.initIDB()
    idb.saveOrder({ trd_date: '20260704', order_no: '10000001', price: 10, status: '48' })
    await new Promise((r) => setTimeout(r, 0))
    idb.saveOrder({ trd_date: '20260704', order_no: '10000001', price: 10, status: '50' })
    await new Promise((r) => setTimeout(r, 0))
    const loaded = await idb.loadOrdersForDate('20260704')
    expect(loaded).toHaveLength(1)
    expect(loaded[0].status).toBe('50')
  })
})


describe('holdings_idb — 跨日 (复合 key prefix 隔离)', () => {
  it('同日多笔 cross-day 读互不影响', async () => {
    await idb.initIDB()
    idb.saveOrder({ trd_date: '20260703', order_no: '10000001', price: 5 })
    idb.saveOrder({ trd_date: '20260704', order_no: '10000001', price: 7 })
    idb.saveTrade({ trd_date: '20260703', order_no: '10000001', trade_id: 'T1' })
    idb.saveTrade({ trd_date: '20260704', order_no: '10000001', trade_id: 'T1' })
    await new Promise((r) => setTimeout(r, 0))

    expect((await idb.loadOrdersForDate('20260703'))[0].price).toBe(5)
    expect((await idb.loadOrdersForDate('20260704'))[0].price).toBe(7)
    expect((await idb.loadTradesForDate('20260703'))[0].trade_id).toBe('T1')
    expect((await idb.loadTradesForDate('20260704'))[0].trade_id).toBe('T1')
  })

  it('clearDate 当日 key 全删, 不影响其他日期 (复合 key prefix 扫描)', async () => {
    await idb.initIDB()
    idb.saveOrder({ trd_date: '20260703', order_no: '10000001' })
    idb.saveOrder({ trd_date: '20260703', order_no: '10000002' })
    idb.saveOrder({ trd_date: '20260704', order_no: '10000001' })
    idb.saveTrade({ trd_date: '20260703', order_no: '10000001', trade_id: 'T1' })
    idb.saveTrade({ trd_date: '20260704', order_no: '10000001', trade_id: 'T1' })
    await new Promise((r) => setTimeout(r, 0))

    await idb.clearDate('20260703')

    expect(await idb.loadOrdersForDate('20260703')).toBeNull()
    expect(await idb.loadTradesForDate('20260703')).toBeNull()
    expect((await idb.loadOrdersForDate('20260704'))[0].order_no).toBe('10000001')
    expect((await idb.loadTradesForDate('20260704'))[0].trade_id).toBe('T1')
  })

  it('clearDate 不存在的 key → 静默成功', async () => {
    await idb.initIDB()
    await expect(idb.clearDate('20991231')).resolves.toBeUndefined()
  })

  it('clearDate(空字符串) → noop', async () => {
    await idb.initIDB()
    await expect(idb.clearDate('')).resolves.toBeUndefined()
  })
})


describe('holdings_idb — fire-and-forget', () => {
  it('saveOrder 不返 Promise (caller 不阻塞)', async () => {
    await idb.initIDB()
    const ret = idb.saveOrder({ trd_date: '20260704', order_no: '10000001', price: 1 })
    expect(ret).toBeUndefined()
  })

  it('saveTrade 不返 Promise', async () => {
    await idb.initIDB()
    const ret = idb.saveTrade({ trd_date: '20260704', order_no: '10000001', trade_id: 'T1' })
    expect(ret).toBeUndefined()
  })

  it('initIDB 复用单例 (多次调只触发一次 openDB)', async () => {
    await idb.initIDB()
    await idb.initIDB()
    await idb.initIDB()
    const { openDB } = await import('../../src/utils/idb')
    // vi.clearAllMocks 之后已重置计数
    expect(openDB).toHaveBeenCalledTimes(1)
  })
})


describe('holdings_idb — IDB 不可用降级', () => {
  it('openDB reject 时 saveOrder 不抛 (只 warn)', async () => {
    const { openDB } = await import('../../src/utils/idb')
    openDB.mockRejectedValueOnce(new Error('IDB unavailable'))

    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})

    // saveOrder 是 fire-and-forget, 不应该 await 出错
    expect(() => idb.saveOrder({ trd_date: '20260704', order_no: '10000001', price: 1 })).not.toThrow()
    await new Promise((r) => setTimeout(r, 5))
    // 警告应该出过（不必严格断言内容）
    expect(warnSpy).toHaveBeenCalled()

    warnSpy.mockRestore()
  })

  it('openDB reject 时 loadOrdersForDate 返 null (不抛)', async () => {
    const { openDB } = await import('../../src/utils/idb')
    openDB.mockRejectedValueOnce(new Error('IDB unavailable'))
    const result = await idb.loadOrdersForDate('20260704')
    expect(result).toBeNull()
  })
})
