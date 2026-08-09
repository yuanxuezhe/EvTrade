/**
 * _setup.js — smoke 测试公共 setup (替代 6.3/6.4 手动验证)
 *
 * 提供 store + IDB + ws 的 mock, 测试 E2E 业务流
 */
import { vi } from 'vitest'

// ─── mock IDB (顶层 hoisted) ─────────────────────────────────
// 用 Map 模拟 indexedDB, 测试调用契约即可 (非真持久化)
//   stores 是模块级单例, 每个测试通过 mockIDB() 拿到引用 → 可读 store 内容做断言
const stores = { orders: new Map(), trades: new Map() }

vi.mock('@/utils/idb', () => ({
  idbGet: vi.fn(async (store, key) => stores[store]?.get(key) || null),
  idbPut: vi.fn(async (store, key, value) => stores[store]?.set(key, value)),
  idbDelete: vi.fn(async (store, key) => stores[store]?.delete(key)),
  idbClear: vi.fn(async (store) => stores[store]?.clear()),
}))

export function mockIDB() {
  stores.orders.clear()
  stores.trades.clear()
  return stores
}

// ─── mock ws push ────────────────────────────────────────────
export function mockWsPush() {
  const handlers = new Map()
  return {
    on: (channel, fn) => handlers.set(channel, fn),
    off: (channel) => handlers.delete(channel),
    simulate: (channel, payload) => handlers.get(channel)?.(payload),
    handlers,
  }
}

// ─── reset all mocks ─────────────────────────────────────────
export function resetAllStores() {
  vi.clearAllMocks()
}