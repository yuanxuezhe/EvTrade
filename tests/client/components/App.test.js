/**
 * App.test.js — 根组件启动生命周期回归测试 (v114.3 day_pnl fix)
 *
 * 复现 BUG: 刷新页面后 token 已持久化 (localStorage) → auth store 同步恢复
 *   isAuthenticated=true → App.vue auth watch (非 immediate) 不触发 →
 *   _startWatchers() (启动 day_pnl recompute) 从未执行 → 当日盈亏列永远为空.
 *
 * 场景: "已登录 mount" (等价于刷新 + token 持久化)
 *   断言 onMounted 必须调用 holdingsStore._startWatchers()
 *   (bootstrap 已调用但 watcher 未启动 → 之前红线)
 */
// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from 'vitest'

vi.mock('@/api', () => ({
  http: {
    get: vi.fn().mockResolvedValue({ data: {} }),
    post: vi.fn().mockResolvedValue({ data: {} }),
  },
  authApi: { me: vi.fn(), login: vi.fn(), logout: vi.fn() },
  userApi: { list: vi.fn(), create: vi.fn(), update: vi.fn(), delete: vi.fn() },
  tokenStorage: { get: vi.fn(() => ''), set: vi.fn(), clear: vi.fn() },
  createWSConnection: vi.fn(),
}))
vi.mock('@/api/t0_stats', () => ({
  t0StatsApi: { getExposure: vi.fn().mockResolvedValue({ positions: [] }) },
}))

import '../setup-view'
import { mountView, flushPromises } from '../setup-view'
import { useAuthStore } from '@/stores/auth'
import { useHoldingsStore } from '@/stores/holdings'
import { useStocksStore } from '@/stores/stocks'
import App from '@/App.vue'

describe('App.vue 已登录 mount → 启动 day_pnl watcher', () => {
  beforeEach(() => {
    // 模拟刷新后 auth 从 localStorage 同步恢复 → isAuthenticated 初始即 true
    const auth = useAuthStore()
    auth.token = 'persisted-token'
    auth.user = { id: 1, role: 'admin' }
  })

  it('onMounted 调用 holdingsStore._startWatchers() (auth watch 非 immediate 不会触发)', async () => {
    const holdings = useHoldingsStore()
    const startSpy = vi.spyOn(holdings, '_startWatchers').mockImplementation(() => {})
    // bootstrap 有真实网络/IDB 副作用, 测试只关心 watcher 是否被启动
    vi.spyOn(holdings, 'bootstrap').mockResolvedValue(undefined)
    const stocks = useStocksStore()
    vi.spyOn(stocks, 'initCache').mockResolvedValue(undefined)

    mountView(App, {
      stubs: {
        Sidebar: true,
        AppHeader: true,
        OperationLog: true,
        BottomNav: true,
        'router-view': { template: '<div class="rv-stub" />' },
      },
    })
    await flushPromises()

    expect(startSpy).toHaveBeenCalled()
  })
})
