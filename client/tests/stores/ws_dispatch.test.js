/**
 * ws_dispatch.js _onOrderCfm 单测 (REQ-TRADE-031)
 *
 * 覆盖:
 *  1. status=50 文案: 之前误说"部成 0/100", 现在说"已报 0/100"
 *  2. 弹窗去重: 相同 status/traded_volume/cancelled_volume 不重复弹
 *  3. 弹窗触发: status 变化 或 累计变化 任一字段变化都弹
 *  4. 新委托 (prev 不存在) → 弹一次
 *
 * 测试方法: 通过 dispatchPayload({type:'ord_cfm', data}) 触发, mock holdings store 控制 prev+applyOrderPush 返值
 */
import { setActivePinia, createPinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// mock 整个 holdings store + element-plus
const applyOrderPushMock = vi.fn()
const ordersRef = []
const tradesRef = []
vi.mock('../../src/stores/holdings', () => ({
  useHoldingsStore: () => ({
    get orders() { return ordersRef },
    get trades() { return tradesRef },
    applyOrderPush: applyOrderPushMock,
  }),
}))

const notifications = []
vi.mock('element-plus', () => ({
  ElNotification: (opts) => { notifications.push(opts) },
  ElMessage: { success: () => {}, error: () => {}, warning: () => {}, info: () => {} },
}))

vi.mock('../../src/utils/logger', () => ({
  makeLogger: () => ({ warn: () => {}, error: () => {}, info: () => {}, debug: () => {}, log: () => {} }),
  default: { warn: () => {}, error: () => {}, info: () => {}, debug: () => {} },
}))

// mock 间接依赖: ws_dispatch → quote → api (避免 api 真加载触发完整链路)
vi.mock('../../src/api', () => ({
  api: { get: vi.fn(), post: vi.fn() },
}))

import { dispatchPayload } from '../../src/stores/ws_dispatch.js'

/** 构造订单推送 payload */
function ordCfm({
  order_no = 'A1',
  stock_code = '000001',
  status = '50',
  volume = 100,
  price = 10.5,
  traded_volume = 0,
  cancelled_volume = 0,
}) {
  return {
    type: 'ord_cfm',
    data: { order_no, stock_code, status, volume, price, traded_volume, cancelled_volume },
  }
}

/** 重置 holdings mock + 通知列表 */
function reset(prevOrder = null) {
  setActivePinia(createPinia())
  notifications.length = 0
  ordersRef.length = 0
  tradesRef.length = 0
  if (prevOrder) ordersRef.push({ ...prevOrder })
  applyOrderPushMock.mockReset()
}

describe('ws_dispatch _onOrderCfm (REQ-TRADE-031)', () => {
  beforeEach(() => reset())

  describe('弹窗文案', () => {
    it('status=50 弹"已报 0/100" (非"部成")', () => {
      reset({ order_no: 'A1', stock_code: '000001', status: '48', traded_volume: 0, cancelled_volume: 0 })
      applyOrderPushMock.mockReturnValue('50')

      dispatchPayload(ordCfm({ status: '50', traded_volume: 0 }))

      expect(notifications).toHaveLength(1)
      expect(notifications[0].title).toBe('委托更新')
      expect(notifications[0].message).toContain('已报')
      expect(notifications[0].message).not.toContain('部成')
      expect(notifications[0].message).toContain('0/100')
      expect(notifications[0].type).toBe('info')  // 已报不是 warning
    })

    it('status=55 弹"部成 N/V" warning', () => {
      reset({ order_no: 'A2', stock_code: '000002', status: '50', traded_volume: 0, cancelled_volume: 0 })
      applyOrderPushMock.mockReturnValue('55')

      dispatchPayload(ordCfm({ order_no: 'A2', stock_code: '000002', status: '55', traded_volume: 30 }))

      expect(notifications).toHaveLength(1)
      expect(notifications[0].message).toContain('部成')
      expect(notifications[0].message).toContain('30/100')
      expect(notifications[0].type).toBe('warning')
    })

    it('status=57 弹"废单" error', () => {
      reset({ order_no: 'A3', stock_code: '000003', status: '50', traded_volume: 0, cancelled_volume: 0 })
      applyOrderPushMock.mockReturnValue('57')

      dispatchPayload(ordCfm({ order_no: 'A3', stock_code: '000003', status: '57' }))

      expect(notifications).toHaveLength(1)
      expect(notifications[0].message).toContain('废单')
      expect(notifications[0].type).toBe('error')
    })

    it('status=56 弹"已成交 100/100" success', () => {
      reset({ order_no: 'A4', stock_code: '000004', status: '55', traded_volume: 50, cancelled_volume: 0 })
      applyOrderPushMock.mockReturnValue('56')

      dispatchPayload(ordCfm({ order_no: 'A4', stock_code: '000004', status: '56', traded_volume: 100 }))

      expect(notifications).toHaveLength(1)
      expect(notifications[0].message).toContain('已成交')
      expect(notifications[0].type).toBe('success')
    })
  })

  describe('弹窗去重 (status/traded_volume/cancelled_volume 三者全等才跳过)', () => {
    it('status 不变 + 累计不变 → 不弹 (重复 ack)', () => {
      reset({ order_no: 'A1', stock_code: '000001', status: '50', traded_volume: 0, cancelled_volume: 0 })
      applyOrderPushMock.mockReturnValue('50')

      // 第一次: prev=50 cum=0, push 50 cum=0 → 三者全等 → 不弹 (user 已报后再 ack)
      dispatchPayload(ordCfm({ status: '50', traded_volume: 0, cancelled_volume: 0 }))
      expect(notifications).toHaveLength(0)  // prev=50 new=50 → 去重

      // 模拟 applyOrderPush 后 prev 已更新到 50 (mock ordersRef 也反映出来)
      ordersRef[0] = { ...ordersRef[0], status: '50', traded_volume: 0, cancelled_volume: 0 }

      // 第二次: status=50 cum=0 cum_cancelled=0 → 三者全等 → 不弹
      dispatchPayload(ordCfm({ status: '50', traded_volume: 0, cancelled_volume: 0 }))
      expect(notifications).toHaveLength(0)  // 仍是 0
    })

    it('status 不变但 traded_volume 增加 → 弹 (部成累计)', () => {
      reset({ order_no: 'A2', stock_code: '000002', status: '55', traded_volume: 30, cancelled_volume: 0 })
      applyOrderPushMock.mockReturnValue('55')

      dispatchPayload(ordCfm({ order_no: 'A2', stock_code: '000002', status: '55', traded_volume: 50 }))

      expect(notifications).toHaveLength(1)
      expect(notifications[0].message).toContain('部成')
      expect(notifications[0].message).toContain('50/100')
    })

    it('status 不变但 cancelled_volume 增加 → 弹 (撤单累计)', () => {
      reset({ order_no: 'A3', stock_code: '000003', status: '54', traded_volume: 0, cancelled_volume: 30 })
      applyOrderPushMock.mockReturnValue('54')

      dispatchPayload(ordCfm({ order_no: 'A3', stock_code: '000003', status: '54', traded_volume: 0, cancelled_volume: 60 }))

      expect(notifications).toHaveLength(1)
      expect(notifications[0].message).toContain('已撤单')
    })

    it('status 变化 (55→56) → 弹', () => {
      reset({ order_no: 'A4', stock_code: '000004', status: '55', traded_volume: 50, cancelled_volume: 0 })
      applyOrderPushMock.mockReturnValue('56')

      dispatchPayload(ordCfm({ order_no: 'A4', stock_code: '000004', status: '56', traded_volume: 100 }))

      expect(notifications).toHaveLength(1)
      expect(notifications[0].message).toContain('已成交')
    })
  })

  describe('边界', () => {
    it('prev 不存在 (新委托) → 弹一次', () => {
      // reset 不传 prevOrder → ordersRef = []
      applyOrderPushMock.mockReturnValue('50')

      dispatchPayload(ordCfm({ status: '50' }))

      expect(notifications).toHaveLength(1)
    })

    it('applyOrderPush 返 null (守门跳过) → 不弹', () => {
      reset({ order_no: 'A1', stock_code: '000001', status: '50', traded_volume: 0, cancelled_volume: 0 })
      applyOrderPushMock.mockReturnValue(null)  // 模拟 v8 trd_date 守门返 null

      dispatchPayload(ordCfm({ status: '50' }))

      expect(notifications).toHaveLength(0)
    })

    it('row 缺 order_no → 跳过', () => {
      dispatchPayload({ type: 'ord_cfm', data: { stock_code: '000001', status: '50' } })
      expect(notifications).toHaveLength(0)
    })
  })
})