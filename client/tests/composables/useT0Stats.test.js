/**
 * useT0Stats.js 单测 (t0-trade-polish-bundle commit 3)
 *
 * 覆盖:
 *   - getStats: 缓存命中 / TTL 过期 / invalidate / force / 错码
 *   - loadAll: 并发 / 部分失败 / 空 codes
 *   - invalidate(code): 单 key / 全清
 */
// @vitest-environment happy-dom
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { useT0Stats } from '../../src/composables/useT0Stats'
import { t0StatsApi } from '../../src/api/t0_stats'

// Mock t0StatsApi.get
vi.mock('../../src/api/t0_stats', () => ({
  t0StatsApi: {
    get: vi.fn(),
  },
}))

const CODE = '600519'
const CODE2 = '000001'
const STATS = { stock_code: CODE, realized_pnl: 100, today_buy_volume: 200, today_sell_volume: 100, win_rate: 0.7, trade_count: 5 }
const STATS2 = { stock_code: CODE2, realized_pnl: -50, today_buy_volume: 0, today_sell_volume: 100, win_rate: 0.5, trade_count: 2 }

beforeEach(() => {
  useT0Stats._resetCache()
  vi.clearAllMocks()
})

describe('getStats', () => {
  it('首次 → fetch + set', async () => {
    t0StatsApi.get.mockResolvedValueOnce(STATS)
    const r = await useT0Stats.getStats(CODE)
    expect(r).toEqual(STATS)
    expect(t0StatsApi.get).toHaveBeenCalledWith(CODE, null, true)
    expect(useT0Stats._size()).toBe(1)
  })

  it('30s 内命中 → 不 fetch', async () => {
    t0StatsApi.get.mockResolvedValueOnce(STATS)
    await useT0Stats.getStats(CODE)
    t0StatsApi.get.mockClear()
    const r2 = await useT0Stats.getStats(CODE)
    expect(r2).toEqual(STATS)
    expect(t0StatsApi.get).not.toHaveBeenCalled()  // 命中缓存
  })

  it('TTL 过期 → 重新 fetch', async () => {
    t0StatsApi.get.mockResolvedValueOnce(STATS)
    await useT0Stats.getStats(CODE)
    // 模拟时间推进 31s
    vi.useFakeTimers()
    vi.advanceTimersByTime(31_000)
    t0StatsApi.get.mockResolvedValueOnce({ ...STATS, realized_pnl: 999 })
    const r = await useT0Stats.getStats(CODE)
    expect(r.realized_pnl).toBe(999)  // 重新 fetch 的值
    expect(t0StatsApi.get).toHaveBeenCalledTimes(2)
    vi.useRealTimers()
  })

  it('force=true → 跳过缓存', async () => {
    t0StatsApi.get.mockResolvedValueOnce(STATS)
    await useT0Stats.getStats(CODE)
    t0StatsApi.get.mockResolvedValueOnce({ ...STATS, realized_pnl: 999 })
    const r = await useT0Stats.getStats(CODE, true)
    expect(r.realized_pnl).toBe(999)
    expect(t0StatsApi.get).toHaveBeenCalledTimes(2)
  })

  it('fetch 失败 → 返 null 不写缓存', async () => {
    t0StatsApi.get.mockRejectedValueOnce(new Error('network'))
    const r = await useT0Stats.getStats(CODE)
    expect(r).toBeNull()
    expect(useT0Stats._size()).toBe(0)
  })

  it('空 code → 返 null', async () => {
    expect(await useT0Stats.getStats(null)).toBeNull()
    expect(await useT0Stats.getStats('')).toBeNull()
    expect(await useT0Stats.getStats(undefined)).toBeNull()
  })

  it('invalidate(code) 后再次 fetch', async () => {
    t0StatsApi.get.mockResolvedValueOnce(STATS)
    await useT0Stats.getStats(CODE)
    expect(useT0Stats._size()).toBe(1)
    useT0Stats.invalidate(CODE)
    expect(useT0Stats._size()).toBe(0)
    t0StatsApi.get.mockResolvedValueOnce({ ...STATS, realized_pnl: 222 })
    const r = await useT0Stats.getStats(CODE)
    expect(r.realized_pnl).toBe(222)
  })
})


describe('loadAll', () => {
  it('并发拉多个标的', async () => {
    t0StatsApi.get.mockImplementation(async (code) => {
      return code === CODE ? STATS : STATS2
    })
    const r = await useT0Stats.loadAll([CODE, CODE2])
    expect(r).toEqual({ [CODE]: STATS, [CODE2]: STATS2 })
    expect(t0StatsApi.get).toHaveBeenCalledTimes(2)
  })

  it('部分失败 → 只返成功的', async () => {
    t0StatsApi.get.mockImplementation(async (code) => {
      if (code === CODE) return STATS
      throw new Error('fail')
    })
    const r = await useT0Stats.loadAll([CODE, CODE2])
    expect(r).toEqual({ [CODE]: STATS })
  })

  it('空 codes → 返 {}', async () => {
    expect(await useT0Stats.loadAll([])).toEqual({})
    expect(await useT0Stats.loadAll(null)).toEqual({})
    expect(t0StatsApi.get).not.toHaveBeenCalled()
  })

  it('去重 + 过滤 falsy', async () => {
    t0StatsApi.get.mockImplementation(async (code) => {
      return code === CODE ? STATS : STATS2
    })
    const r = await useT0Stats.loadAll([CODE, null, CODE, ''])
    expect(Object.keys(r).length).toBe(1)
    expect(r[CODE]).toEqual(STATS)
  })
})


describe('invalidate', () => {
  it('invalidate(code) → 删单个', async () => {
    t0StatsApi.get.mockImplementation(async (code) => (code === CODE ? STATS : STATS2))
    await useT0Stats.loadAll([CODE, CODE2])
    expect(useT0Stats._size()).toBe(2)
    useT0Stats.invalidate(CODE)
    expect(useT0Stats._size()).toBe(1)
  })

  it('invalidate(null) → 全部失效', async () => {
    t0StatsApi.get.mockImplementation(async (code) => (code === CODE ? STATS : STATS2))
    await useT0Stats.loadAll([CODE, CODE2])
    useT0Stats.invalidate(null)
    expect(useT0Stats._size()).toBe(0)
  })

  it('invalidateAll() → 全部失效', async () => {
    t0StatsApi.get.mockImplementation(async (code) => (code === CODE ? STATS : STATS2))
    await useT0Stats.loadAll([CODE, CODE2])
    useT0Stats.invalidateAll()
    expect(useT0Stats._size()).toBe(0)
  })
})