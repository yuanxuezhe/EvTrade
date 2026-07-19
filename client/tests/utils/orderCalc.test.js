/**
 * orderCalc.test.js — 5 个纯函数单测（REQ-FE-009.9）
 *
 * 覆盖：
 * - normalizeTrade: amount = price × volume 本地算
 * - recomputeOrderFromTrade: 增量累计 + avg_price + status 推断
 * - metaMerge: PK + 元数据覆盖，累计字段保留 ref + status 重推断
 * - flattenCancelledByRow: cancel-row 反向抹平 orig.cancelled_volume = orig.volume + status
 * - normalizeOrder: bootstrap 用，重算 avg_price + status
 */

import { describe, it, expect } from 'vitest'
import {
  normalizeTrade,
  recomputeOrderFromTrade,
  metaMerge,
  flattenCancelledByRow,
  normalizeOrder,
} from '../../src/utils/orderCalc'

// ──── normalizeTrade ────

describe('normalizeTrade', () => {
  it('amount = price × volume', () => {
    expect(normalizeTrade({ price: 12.5, volume: 100 }).amount).toBe(1250)
  })

  it('amount = 0 when volume = 0', () => {
    expect(normalizeTrade({ price: 12.5, volume: 0 }).amount).toBe(0)
  })

  it('amount = 0 when price = 0', () => {
    expect(normalizeTrade({ price: 0, volume: 100 }).amount).toBe(0)
  })

  it('preserves other fields', () => {
    const t = normalizeTrade({
      trade_id: 'TID-1', order_no: '10000001',
      price: 10, volume: 50, stock_code: '600030.SH',
    })
    expect(t.trade_id).toBe('TID-1')
    expect(t.order_no).toBe('10000001')
    expect(t.stock_code).toBe('600030.SH')
  })

  it('treats string prices/volumes as numbers', () => {
    expect(normalizeTrade({ price: '12.5', volume: '100' }).amount).toBe(1250)
  })
})

// ──── recomputeOrderFromTrade ────

describe('recomputeOrderFromTrade', () => {
  it('increments traded_volume + traded_amount', () => {
    const order = { order_no: '1', traded_volume: 30, traded_amount: 375, avg_price: 12.5 }
    const trade = { price: 12.5, volume: 70 }
    const next = recomputeOrderFromTrade(order, trade)
    expect(next.traded_volume).toBe(100)
    expect(next.traded_amount).toBe(1250)
    expect(next.avg_price).toBe(12.5)
  })

  it('avg_price = 0 when traded_volume = 0', () => {
    const order = { traded_volume: 0, traded_amount: 0, avg_price: 0 }
    const next = recomputeOrderFromTrade(order, { price: 12.5, volume: 0 })
    expect(next.avg_price).toBe(0)
    expect(next.traded_volume).toBe(0)
  })

  it('infers status from cumulative (no broker_status)', () => {
    // cum=100/100 → broker 56 (已成)
    const order = { traded_volume: 100, traded_amount: 1250, volume: 100 }
    const next = recomputeOrderFromTrade(order, { price: 12.5, volume: 0 })
    expect(next.status).toBe('56')
  })

  it('infers status partial fill → broker 55 (部成)', () => {
    // cum=30/100 → broker 55
    const order = { traded_volume: 30, traded_amount: 375, volume: 100 }
    const next = recomputeOrderFromTrade(order, { price: 12.5, volume: 0 })
    expect(next.status).toBe('55')
  })

  it('preserves other order fields', () => {
    const order = {
      order_no: 'X', trd_date: '20260702', stock_code: '600030.SH',
      traded_volume: 0, traded_amount: 0,
    }
    const next = recomputeOrderFromTrade(order, { price: 10, volume: 50 })
    expect(next.order_no).toBe('X')
    expect(next.stock_code).toBe('600030.SH')
  })
})

// ──── metaMerge ────

describe('metaMerge', () => {
  const ref = {
    order_no: '10000003', trd_date: '20260702',
    order_id: 'OID-OLD', stock_code: '600030.SH',
    price: 10, volume: 100,
    traded_volume: 30, traded_amount: 300, avg_price: 10,
    cancelled_volume: 0, status: '50',
  }

  // v76 (REQ-TRADE-027): row 含 4 累计字段时 row 优先 (broker 推完整累计值用最新).
  //   历史注释 "ref 保留" 是设计意图但实现漏字段; 现在改为 row ?? ref ?? 0 与 v65/v66 一致.
  it('uses row accumulator values when both row and ref have them (broker full update)', () => {
    const row = {
      order_no: '10000003', order_id: 'BROKER-OID-X',
      traded_volume: 999, traded_amount: 99999, avg_price: 999,
      cancelled_volume: 999, status: '53',
    }
    const merged = metaMerge(row, ref)
    expect(merged.traded_volume).toBe(999)       // row 优先
    expect(merged.traded_amount).toBe(99999)     // row 优先
    expect(merged.avg_price).toBe(999)           // row 优先
    expect(merged.cancelled_volume).toBe(999)    // row 优先
  })

  it('overwrites PK + metadata fields from row', () => {
    const row = {
      order_no: '10000003',
      order_id: 'BROKER-OID-X',
      order_time: '09:30:00',
      stock_code: '600020.SH',
      order_type: '24',
      price: 11, volume: 200,
      status_msg: '已报',
    }
    const merged = metaMerge(row, ref)
    expect(merged.order_id).toBe('BROKER-OID-X')
    expect(merged.stock_code).toBe('600020.SH')
    expect(merged.order_type).toBe('24')
    expect(merged.price).toBe(11)
    expect(merged.volume).toBe(200)
    expect(merged.order_time).toBe('09:30:00')
    expect(merged.status_msg).toBe('已报')
  })

  it('infers status from row.status (broker_status signal)', () => {
    // ref status=50 (非终态) + broker 推 53 (部成部撤) + 累计 30/100 → broker 53
    const row = { order_no: '10000003', status: '53' }
    const merged = metaMerge(row, ref)
    expect(merged.status).toBe('53')
  })

  it('handles missing row.status (no broker_status signal)', () => {
    const row = { order_no: '10000003' }
    const merged = metaMerge(row, ref)
    // ref status=50 非终态 + cum 30/100 → broker 55 (部成)
    expect(merged.status).toBe('55')
  })

  it('uses ref defaults when row fields missing', () => {
    const empty = { order_no: '1' }
    const merged = metaMerge(empty, ref)
    expect(merged.stock_code).toBe('600030.SH')  // from ref
    expect(merged.price).toBe(10)                 // from ref
  })

  // v76 (REQ-TRADE-027): 下单后 _upsertToHoldings 走 ref=undefined (空 ref = {})，
  //   row 必含 4 累计字段 (server 端 OrderOut 一定返), merged 必须保留 row 值不能丢.
  //   修复前 bug: metaMerge 漏 4 行透传 → 成交量/成交金额/均价/撤单量列全部 0,
  //   只得等下次 ws push (broker ord_cfm) 覆盖 → 用户感知"下单后委托不刷新".
  describe('v76: passes through accumulator fields from row on first open', () => {
    const orderRow = {
      order_no: '10000005', trd_date: '20260718',
      stock_code: '600519.SH', price: 1800, volume: 100,
      traded_volume: 0, traded_amount: 0, avg_price: 0,
      cancelled_volume: 0, status: '50',
    }
    it('ref=undefined 走默认 {} 时透传 row 累计字段', () => {
      const merged = metaMerge(orderRow)
      expect(merged.traded_volume).toBe(0)
      expect(merged.traded_amount).toBe(0)
      expect(merged.avg_price).toBe(0)
      expect(merged.cancelled_volume).toBe(0)
    })
    it('ref={} 空对象时同上 (applyOrderPush open 路径)', () => {
      const merged = metaMerge(orderRow, {})
      expect(merged.traded_volume).toBe(0)
      expect(merged.traded_amount).toBe(0)
      expect(merged.avg_price).toBe(0)
      expect(merged.cancelled_volume).toBe(0)
    })
    // v77 (REQ-TRADE-028): ws push 阶段 B 异步竞态 (commit 9-A 后)，ref 可能显式传 null.
    //   v76 默认参数 {}= ref={} 时没问题，但 ref=null 时 ref.task_id 触发
    //   "Cannot read properties of null" 崩溃. 必须 ?? {} 兜底.
    it('ref=null 显式 null 时不能崩 (vs76 兼容 ws_dispatch 异步竞态)', () => {
      expect(() => metaMerge(orderRow, null)).not.toThrow()
      const merged = metaMerge(orderRow, null)
      expect(merged.traded_volume).toBe(0)
      expect(merged.task_id).toBeNull()
      expect(merged.strategy_type).toBe(0)
    })
    it('ref 有累计值, row 不含 4 字段时保留 ref (broker ord_cfm 增量推送)', () => {
      const cfmRow = { order_no: '10000003', status: '55' } // 模拟 broker ord_cfm 只推 status
      const localRef = {
        order_no: '10000003',
        traded_volume: 30, traded_amount: 300, avg_price: 10,
        cancelled_volume: 0,
      }
      const merged = metaMerge(cfmRow, localRef)
      expect(merged.traded_volume).toBe(30)
      expect(merged.traded_amount).toBe(300)
      expect(merged.avg_price).toBe(10)
      expect(merged.cancelled_volume).toBe(0)
    })
    it('row+ref 都含 4 字段时 row 优先 (broker 推完整累计值)', () => {
      const rowFull = {
        order_no: '10000006',
        traded_volume: 50, traded_amount: 5000, avg_price: 100,
        cancelled_volume: 0, status: '55',
      }
      const refStale = {
        order_no: '10000006',
        traded_volume: 30, traded_amount: 3000, avg_price: 100,
        cancelled_volume: 0,
      }
      const merged = metaMerge(rowFull, refStale)
      expect(merged.traded_volume).toBe(50)
      expect(merged.traded_amount).toBe(5000)
    })
  })
})

// ──── flattenCancelledByRow ────

describe('flattenCancelledByRow', () => {
  it('returns [] when user_def does not start with CANCEL:', () => {
    const list = [{ order_no: 'X', volume: 100, cancelled_volume: 0 }]
    expect(flattenCancelledByRow({ user_def: 'foo' }, list)).toEqual([])
  })

  it('returns [] when orig order not found', () => {
    const list = [{ order_no: 'OTHER', volume: 100 }]
    expect(flattenCancelledByRow({ user_def: 'CANCEL:MISSING' }, list)).toEqual([])
  })

  it('flattens orig.cancelled_volume = orig.volume', () => {
    const list = [{
      order_no: '10000004', volume: 100,
      cancelled_volume: 0, status: '50',
    }]
    const affected = flattenCancelledByRow(
      { user_def: 'CANCEL:10000004', order_flag: 1 },
      list,
    )
    expect(affected).toHaveLength(1)
    expect(list[0].cancelled_volume).toBe(100)
  })

  it('updates orig.status via inferOrderStatus', () => {
    // ref status=50 (非终态) + cancelled=100 (volume) → broker 54 (已撤)
    const list = [{
      order_no: '10000004', volume: 100,
      cancelled_volume: 0, status: '50', traded_volume: 30, traded_amount: 375,
    }]
    flattenCancelledByRow({ user_def: 'CANCEL:10000004', order_flag: 1 }, list)
    expect(list[0].status).toBe('54')
  })

  it('preserves orig order identity', () => {
    const list = [{
      order_no: '10000004', stock_code: '600030.SH',
      volume: 100, cancelled_volume: 0,
    }]
    flattenCancelledByRow({ user_def: 'CANCEL:10000004', order_flag: 1 }, list)
    expect(list[0].order_no).toBe('10000004')
    expect(list[0].stock_code).toBe('600030.SH')
  })
})

// ──── normalizeOrder ────

describe('normalizeOrder', () => {
  it('recomputes avg_price from traded_amount / traded_volume', () => {
    const o = normalizeOrder({
      traded_volume: 100, traded_amount: 1250, avg_price: 0,
    })
    expect(o.avg_price).toBe(12.5)
  })

  it('avg_price = 0 when traded_volume = 0', () => {
    const o = normalizeOrder({
      traded_volume: 0, traded_amount: 0, avg_price: 0,
    })
    expect(o.avg_price).toBe(0)
  })

  it('infers status from cumulative', () => {
    // cum=100/100 + status='48' (broker 未报) → broker 56 (已成, 累计推断)
    const o = normalizeOrder({
      volume: 100, traded_volume: 100, traded_amount: 1250, status: '48',
    })
    expect(o.status).toBe('56')
  })

  it('infers status partial fill → broker 55 (部成)', () => {
    const o = normalizeOrder({
      volume: 100, traded_volume: 30, traded_amount: 375, status: '48',
    })
    expect(o.status).toBe('55')
  })

  it('preserves original fields', () => {
    const o = normalizeOrder({
      order_no: 'X', trd_date: '20260702', stock_code: '600030.SH',
      volume: 100, traded_volume: 100, traded_amount: 1250,
    })
    expect(o.order_no).toBe('X')
    expect(o.trd_date).toBe('20260702')
    expect(o.stock_code).toBe('600030.SH')
  })
})