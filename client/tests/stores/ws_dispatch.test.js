/**
 * ws_dispatch.js _onOrderCfm + _onTradeCfm 单测 (REQ-TRADE-032)
 *
 * 覆盖:
 *  1. 委托弹窗文案: trd_date order_no code label (后端只推 50/57, 无多分支)
 *  2. 成交弹窗文案: trd_date order_no code volume@price status
 *  3. 控制台日志: 委托 + 成交 都 log.info
 *  4. 前端不做去重: 重复 ws 推送也弹 (后端已守门只推 50/57)
 *  5. applyOrderPush 返 null → 不弹
 *  6. row 缺 order_no/trade_id → 跳过
 */

import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'

// Mock logger: 收集 info 调用用于断言日志
const infoCalls = []
vi.mock('../../src/utils/logger', () => ({
  makeLogger: () => ({
    warn: vi.fn(),
    error: vi.fn(),
    info: (...args) => infoCalls.push(args),
    debug: () => {},
    log: () => {},
  }),
  default: { warn: () => {}, error: () => {}, info: () => {}, debug: () => {}, log: () => {} },
}))

// Mock ElNotification: 收集弹窗调用
const notifications = []
vi.mock('element-plus', () => ({
  ElNotification: (opts) => notifications.push(opts),
}))

// Mock STATUS_LABEL from format.js
vi.mock('../../src/utils/format', () => ({
  STATUS_LABEL: {
    '48': '未报', '49': '待报', '50': '已报', '51': '已报待撤',
    '52': '部成待撤', '53': '部撤', '54': '已撤', '55': '部成',
    '56': '已成', '57': '废单',
  },
}))

// Mock holdings store
const ordersRef = []
const tradesRef = []
const applyOrderPushMock = vi.fn()
const applyTradePushMock = vi.fn()
vi.mock('../../src/stores/holdings', () => ({
  useHoldingsStore: () => ({
    orders: ordersRef,
    trades: tradesRef,
    applyOrderPush: applyOrderPushMock,
    applyTradePush: applyTradePushMock,
  }),
}))

import { dispatchPayload } from '../../src/stores/ws_dispatch'

const ordCfm = (overrides = {}) => ({
  order_no: 'A1',
  trd_date: '20260719',
  stock_code: '000001.SZ',
  status: '50',
  ...overrides,
})

const trdCfm = (overrides = {}) => ({
  trade_id: 'T1',
  trd_date: '20260719',
  order_no: 'A1',
  stock_code: '000001.SZ',
  volume: 100,
  price: 10.5,
  order_type: '23',
  ...overrides,
})

describe('ws_dispatch _onOrderCfm (REQ-TRADE-032)', () => {
  beforeEach(() => {
    notifications.length = 0
    infoCalls.length = 0
    ordersRef.length = 0
    applyOrderPushMock.mockReset()
  })

  describe('弹窗文案 (新格式: trd_date order_no code label)', () => {
    it('status=50 弹"20260719 A1 000001.SZ 已报"', () => {
      applyOrderPushMock.mockReturnValue('50')
      dispatchPayload({ type: 'ord_cfm', data: ordCfm({ status: '50' }) })
      expect(notifications).toHaveLength(1)
      expect(notifications[0].title).toBe('委托确认')
      expect(notifications[0].message).toBe('20260719 A1 000001.SZ 已报')
    })

    it('status=57 弹"20260719 A1 000001.SZ 废单"', () => {
      applyOrderPushMock.mockReturnValue('57')
      dispatchPayload({ type: 'ord_cfm', data: ordCfm({ status: '57' }) })
      expect(notifications[0].message).toBe('20260719 A1 000001.SZ 废单')
    })
  })

  describe('前端不做去重 (REQ-TRADE-032)', () => {
    it('同状态重复 ws 推送 → 仍弹 (后端已守门只推 50/57, 收到即通知)', () => {
      applyOrderPushMock.mockReturnValue('50')
      // 模拟同一订单 ws 推 2 次 (broker 增量 ack)
      dispatchPayload({ type: 'ord_cfm', data: ordCfm({ status: '50' }) })
      dispatchPayload({ type: 'ord_cfm', data: ordCfm({ status: '50' }) })
      // 两次都弹, 不去重
      expect(notifications).toHaveLength(2)
    })
  })

  describe('控制台日志', () => {
    it('委托推送打 log.info 含 trd_date/order_no/code/status', () => {
      applyOrderPushMock.mockReturnValue('50')
      dispatchPayload({ type: 'ord_cfm', data: ordCfm({ status: '50' }) })
      const ordLogs = infoCalls.filter(c => c[0]?.includes?.('[ord_cfm]'))
      expect(ordLogs).toHaveLength(1)
      expect(ordLogs[0][0]).toContain('trd_date=20260719')
      expect(ordLogs[0][0]).toContain('order_no=A1')
      expect(ordLogs[0][0]).toContain('code=000001.SZ')
      expect(ordLogs[0][0]).toContain('status=50')
    })
  })

  describe('边界', () => {
    it('applyOrderPush 返 null → 不弹 (v13 守门)', () => {
      applyOrderPushMock.mockReturnValue(null)
      dispatchPayload({ type: 'ord_cfm', data: ordCfm() })
      expect(notifications).toHaveLength(0)
    })

    it('row 缺 order_no → 跳过', () => {
      dispatchPayload({ type: 'ord_cfm', data: ordCfm({ order_no: undefined }) })
      expect(notifications).toHaveLength(0)
      expect(applyOrderPushMock).not.toHaveBeenCalled()
    })
  })
})

describe('ws_dispatch _onTradeCfm (REQ-TRADE-032)', () => {
  beforeEach(() => {
    notifications.length = 0
    infoCalls.length = 0
    ordersRef.length = 0
    tradesRef.length = 0
    applyTradePushMock.mockReset()
  })

  describe('弹窗文案 (新格式: trd_date order_no code volume@price status)', () => {
    it('订单状态=55 部成 → 弹"20260719 A1 000001.SZ 100@10.5 部成"', () => {
      ordersRef.push({ order_no: 'A1', status: '55' })
      dispatchPayload({ type: 'trd_cfm', data: trdCfm({ volume: 100, price: 10.5 }) })
      expect(notifications).toHaveLength(1)
      expect(notifications[0].title).toBe('成交通知')
      expect(notifications[0].message).toBe('20260719 A1 000001.SZ 100@10.5 部成')
    })

    it('订单状态=56 已成 → 弹"20260719 A1 000001.SZ 100@10.5 已成"', () => {
      ordersRef.push({ order_no: 'A1', status: '56' })
      dispatchPayload({ type: 'trd_cfm', data: trdCfm() })
      expect(notifications[0].message).toBe('20260719 A1 000001.SZ 100@10.5 已成')
    })

    it('找不到原订单 (race) → 状态兜底 -', () => {
      ordersRef.length = 0
      dispatchPayload({ type: 'trd_cfm', data: trdCfm() })
      expect(notifications[0].message).toBe('20260719 A1 000001.SZ 100@10.5 -')
    })
  })

  describe('控制台日志', () => {
    it('成交推送打 log.info 含 trd_date/order_no/code/volume@price/status', () => {
      ordersRef.push({ order_no: 'A1', status: '55' })
      dispatchPayload({ type: 'trd_cfm', data: trdCfm() })
      const trdLogs = infoCalls.filter(c => c[0]?.includes?.('[trd_cfm]'))
      expect(trdLogs).toHaveLength(1)
      expect(trdLogs[0][0]).toContain('trd_date=20260719')
      expect(trdLogs[0][0]).toContain('order_no=A1')
      expect(trdLogs[0][0]).toContain('000001.SZ')
      expect(trdLogs[0][0]).toContain('100@10.5')
      expect(trdLogs[0][0]).toContain('status=部成')
    })
  })

  describe('边界', () => {
    it('row 缺 trade_id → 跳过', () => {
      dispatchPayload({ type: 'trd_cfm', data: trdCfm({ trade_id: undefined }) })
      expect(notifications).toHaveLength(0)
      expect(applyTradePushMock).not.toHaveBeenCalled()
    })
  })
})