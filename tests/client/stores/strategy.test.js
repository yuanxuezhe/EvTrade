/**
 * strategy.test.js — strategy store 单测（change strategy_trade task 10）
 *
 * 覆盖（8 用例）：
 * - loadStrategies 拉 + 过滤 + lastUpdated 时间戳
 * - loadStrategy 单个 detail 写入缓存
 * - createStrategy 追加
 * - updateStrategy in-place 替换
 * - deleteStrategy 移除 + 清 audit 缓存
 * - controlStrategy 改本地 status（clear_now 不改 status）
 * - loadFlagDefinitions 缓存
 * - loadAudit 按 (id, trdDate) 缓存 + appendAudit 推入头部
 */
import { setActivePinia, createPinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// mock api/strategy.js（store 仅依赖此模块）
vi.mock('@/api/strategy', () => ({
  strategyApi: {
    list: vi.fn(),
    create: vi.fn(),
    getById: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
    control: vi.fn(),
    getAudit: vi.fn(),
    getFlagDefinitions: vi.fn(),
  },
}))

import { useStrategyStore } from '@/stores/strategy'
import { strategyApi } from '@/api/strategy'

const _mock = strategyApi  // 简化取 mock

function _mkStrategy(over = {}) {
  return {
    id: 1,
    user_id: 10,
    stock_code: '600519.SH',
    type: 'general',
    reference_price: 10.0,
    status: 'active',
    base_volume: 100,
    note: '',
    regimes: [],
    created_at: '2026-07-06T00:00:00',
    updated_at: '2026-07-06T00:00:00',
    ...over,
  }
}

describe('strategy store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('loadStrategies 拉全列表 + 写 strategies + 更新时间戳', async () => {
    const s1 = _mkStrategy({ id: 1, stock_code: '600519.SH' })
    const s2 = _mkStrategy({ id: 2, stock_code: '000001.SZ', type: 't0' })
    _mock.list.mockResolvedValueOnce([s1, s2])

    const store = useStrategyStore()
    const before = Date.now()
    await store.loadStrategies()

    expect(_mock.list).toHaveBeenCalledWith({})
    expect(store.strategies).toHaveLength(2)
    expect(store.strategies[0].stock_code).toBe('600519.SH')
    expect(store.strategies[1].type).toBe('t0')
    expect(store.lastUpdated).toBeGreaterThanOrEqual(before)
    expect(store.loading).toBe(false)
  })

  it('loadStrategies 支持 status/type 过滤参数透传', async () => {
    _mock.list.mockResolvedValueOnce([])
    const store = useStrategyStore()
    await store.loadStrategies({ status: 'active', type: 't0' })

    expect(_mock.list).toHaveBeenCalledWith({ status: 'active', type: 't0' })
  })

  it('loadStrategy 单条 detail → upsert 进缓存', async () => {
    const store = useStrategyStore()
    // 先放一条 id=1 的占位
    store.strategies.push(_mkStrategy({ id: 1, note: 'old' }))
    _mock.getById.mockResolvedValueOnce(_mkStrategy({ id: 1, note: 'new' }))

    const res = await store.loadStrategy(1)

    expect(res.note).toBe('new')
    expect(store.strategies).toHaveLength(1) // in-place 替换，不追加
    expect(store.strategies[0].note).toBe('new')
  })

  it('createStrategy 追加新策略到列表', async () => {
    const created = _mkStrategy({ id: 99, stock_code: '600000.SH' })
    _mock.create.mockResolvedValueOnce(created)
    const store = useStrategyStore()
    // pending 守门
    expect(store._isPending('create')).toBe(false)
    const p = store.createStrategy({ stock_code: '600000.SH', regimes: [] })
    expect(store._isPending('create')).toBe(true)
    const res = await p

    expect(res.id).toBe(99)
    expect(store.strategies).toHaveLength(1)
    expect(store.strategies[0].id).toBe(99)
    expect(store._isPending('create')).toBe(false)
  })

  it('updateStrategy in-place 替换（不追加）', async () => {
    const store = useStrategyStore()
    store.strategies.push(_mkStrategy({ id: 5, status: 'active', base_volume: 100 }))
    _mock.update.mockResolvedValueOnce(_mkStrategy({ id: 5, status: 'paused', base_volume: 200 }))

    const res = await store.updateStrategy(5, { status: 'paused', base_volume: 200 })

    expect(_mock.update).toHaveBeenCalledWith(5, { status: 'paused', base_volume: 200 })
    expect(res.status).toBe('paused')
    expect(store.strategies).toHaveLength(1)
    expect(store.strategies[0].status).toBe('paused')
    expect(store.strategies[0].base_volume).toBe(200)
  })

  it('deleteStrategy 移除 + 清 audit 缓存', async () => {
    const store = useStrategyStore()
    store.strategies.push(_mkStrategy({ id: 7 }))
    store.auditCache = { 7: { 20260706: [{ id: 'a' }] } }
    _mock.delete.mockResolvedValueOnce()

    await store.deleteStrategy(7)

    expect(_mock.delete).toHaveBeenCalledWith(7)
    expect(store.strategies).toHaveLength(0)
    expect(store.auditCache[7]).toBeUndefined()
  })

  it('controlStrategy 调 API + 改本地 status（clear_now 不改 status）', async () => {
    const store = useStrategyStore()
    store.strategies.push(_mkStrategy({ id: 11, status: 'active' }))

    // pause → status=paused
    _mock.control.mockResolvedValueOnce({ ok: true, action: 'pause', strategy_id: 11, status: 'paused' })
    await store.controlStrategy(11, 'pause')
    expect(store.strategies[0].status).toBe('paused')

    // clear_now → 后端不返回 status（None）；本地 status 不变
    _mock.control.mockResolvedValueOnce({ ok: true, action: 'clear_now', strategy_id: 11 })
    await store.controlStrategy(11, 'clear_now')
    expect(store.strategies[0].status).toBe('paused') // 保持 pause 不变
  })

  it('loadFlagDefinitions 缓存 + getters 按 status/type 分组', async () => {
    const flags = [
      { code: 'ma_bullish', name: '均线多头', category: 'trend', description: 'MA 上行' },
      { code: 'rsi_over', name: 'RSI 超买', category: 'momentum', description: '>70' },
    ]
    _mock.getFlagDefinitions.mockResolvedValueOnce({ list: flags })
    const store = useStrategyStore()
    await store.loadFlagDefinitions()

    expect(store.flagDefinitions).toHaveLength(2)
    expect(store.flagDefinitions[0].code).toBe('ma_bullish')

    // 准备多类型多状态策略
    store.strategies.push(
      _mkStrategy({ id: 1, type: 'general', status: 'active' }),
      _mkStrategy({ id: 2, type: 'general', status: 'paused' }),
      _mkStrategy({ id: 3, type: 't0', status: 'active' }),
      _mkStrategy({ id: 4, type: 't0', status: 'stopped' }),
    )

    expect(store.activeStrategies.map((s) => s.id)).toEqual([1, 3])
    expect(store.pausedStrategies.map((s) => s.id)).toEqual([2])
    expect(store.stoppedStrategies.map((s) => s.id)).toEqual([4])
    expect(store.generalStrategies.map((s) => s.id)).toEqual([1, 2])
    expect(store.t0Strategies.map((s) => s.id)).toEqual([3, 4])
    expect(store.getById(2)?.status).toBe('paused')
    expect(store.getById(999)).toBeUndefined()
  })

  it('loadAudit + appendAudit 按 (id, trdDate) 增量缓存', async () => {
    const store = useStrategyStore()
    const audit1 = [
      { id: 'a1', strategy_id: 1, trigger_type: 'grid_triggered', trd_date: '20260706' },
      { id: 'a2', strategy_id: 1, trigger_type: 'regime_changed', trd_date: '20260706' },
    ]
    _mock.getAudit.mockResolvedValueOnce(audit1)
    const res = await store.loadAudit(1, '20260706')

    expect(res).toHaveLength(2)
    expect(store.getAudit(1, '20260706')).toHaveLength(2)

    // 增量推入头部
    store.appendAudit(1, '20260706', { id: 'a3', strategy_id: 1, trigger_type: 'a3', trd_date: '20260706' })
    expect(store.getAudit(1, '20260706')).toHaveLength(3)
    expect(store.getAudit(1, '20260706')[0].id).toBe('a3')

    // 不同 trd_date 隔离
    expect(store.getAudit(1, '20260705')).toEqual([])
  })
})
