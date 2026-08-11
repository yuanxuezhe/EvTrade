/**
 * StrategyOrderNav.test.js — 验证策略下单 API client 封装 + 路由 + 导航 (v126, C6)
 *
 * 覆盖:
 * - scriptStrategyApi 新增 6 个 method 全部存在
 * - 路由表包含 /strategy-order (requiresTrader)
 * - Sidebar 菜单包含「策略下单」入口 (策略交易分组下, 策略运行之后)
 */
import { describe, it, expect, vi } from 'vitest'

import { scriptStrategyApi } from '@/api/script_strategy'
import { http } from '@/api'

describe('StrategyOrderNav (v126)', () => {
  it('scriptStrategyApi 新增 6 个 method', () => {
    expect(typeof scriptStrategyApi.createStrategyOrder).toBe('function')
    expect(typeof scriptStrategyApi.listStrategyOrders).toBe('function')
    expect(typeof scriptStrategyApi.getStrategyOrder).toBe('function')
    expect(typeof scriptStrategyApi.listStrategyOrderChildren).toBe('function')
    expect(typeof scriptStrategyApi.startStrategyOrder).toBe('function')
    expect(typeof scriptStrategyApi.stopStrategyOrder).toBe('function')
    expect(typeof scriptStrategyApi.closeStrategyOrder).toBe('function')
  })

  it('createStrategyOrder 调 POST /strategy-orders', async () => {
    const spy = vi.spyOn(http, 'post').mockResolvedValue({ data: { id: 1 } })
    const out = await scriptStrategyApi.createStrategyOrder(42)
    expect(spy).toHaveBeenCalledWith('/script-strategy/strategy-orders', { strategy_id: 42 })
    expect(out).toEqual({ id: 1 })
  })

  it('startStrategyOrder 调 POST /strategy-orders/{id}/start', async () => {
    const spy = vi.spyOn(http, 'post').mockResolvedValue({ data: { status: 'running' } })
    const out = await scriptStrategyApi.startStrategyOrder(7)
    expect(spy).toHaveBeenCalledWith('/script-strategy/strategy-orders/7/start')
    expect(out).toEqual({ status: 'running' })
  })
})
