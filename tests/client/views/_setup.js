/**
 * _setup.js — view 测试公共 setup (change: add-view-level-vitest-stack)
 *
 * 提供 view 测试的 mock 数据 helpers
 * api mock 在 setup-view.js 中统一处理 (vi.mock 自动 hoist)
 */
import { vi } from 'vitest'

// ─── mock 数据 helper ─────────────────────────────────────────
export function makeOrder(overrides = {}) {
  return {
    trd_date: '20260701',
    order_time: '09:30:00',
    order_no: '00000001',
    order_flag: 0,
    stock_code: '600030.SH',
    order_type: '23',
    volume: 100,
    price: 12.34,
    traded_volume: 0,
    traded_amount: 0,
    status: '50',
    status_msg: '已报',
    order_id: 'SH|000001',
    remark: '',
    ...overrides
  }
}

export function makeTrade(overrides = {}) {
  return {
    trd_date: '20260701',
    trade_time: '09:30:01',
    trade_id: 'T00000001',
    order_no: '00000001',
    stock_code: '600030.SH',
    order_type: '23',
    trade_type: 0,
    volume: 100,
    price: 12.34,
    amount: 1234.0,
    ...overrides
  }
}

// ─── api mock 重置 helper ─────────────────────────────────────
export function resetApiMocks() {
  // vi.mocked 返回 mock fn, mockClear 重置调用记录
  // 各 api.fn 在 setup-view.js 中 mock
  // 这里仅提供 convenience
  vi.clearAllMocks()
}