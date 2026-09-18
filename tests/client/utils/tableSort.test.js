/**
 * tableSort.test.js — DataTableView 排序纯函数单测 (2026-09-18, REQ-FE-540)
 *
 * 覆盖:
 *  - sortCompare: null 兜底 (与原 DataTableView 行为 1:1 — 升序 null 末位, 降序 null 首位)
 *                / 数字 / 字符串
 *  - getSortValue: 列定义有 sortFn 优先; 无 sortFn fallback row[col.key]; col.key 缺省返回 undefined
 *  - 与 DataTableView 排序链路 1:1: [...data].sort((a,b)=>sortCompare(getSortValue(a,col), getSortValue(b,col), dir))
 *
 * ⚠️ null 行为契约（继承自原 DataTableView，未变更）:
 *   - 升序 (dir=1): va=null → return 1 → null 排后 (末位)
 *   - 降序 (dir=-1): va=null → return -1 → null 排前 (首位)
 *   这是 el-table 原生排序的默认行为, 改 sortFn 后保持不变 (向后兼容)
 */

import { describe, it, expect } from 'vitest'
import { sortCompare, getSortValue } from '../../../client/src/utils/tableSort'

describe('tableSort.sortCompare — null 兜底 (与原 DataTableView 行为 1:1)', () => {
  it('升序: va=null → return dir=1 → null 排后 (末位)', () => {
    const arr = [5, null]
    arr.sort((a, b) => sortCompare(a, b, 1))
    expect(arr).toEqual([5, null])
  })

  it('降序: va=null → return dir=-1 → null 排前 (首位, 原行为)', () => {
    const arr = [5, null]
    arr.sort((a, b) => sortCompare(a, b, -1))
    expect(arr).toEqual([null, 5])
  })

  it('null vs null: 顺序保持', () => {
    expect(sortCompare(null, null, 1)).toBe(0)
    expect(sortCompare(null, null, -1)).toBe(0)
    expect(sortCompare(undefined, undefined, 1)).toBe(0)
  })

  it('undefined 同样兜底', () => {
    const arr = [5, undefined]
    arr.sort((a, b) => sortCompare(a, b, 1))
    expect(arr).toEqual([5, undefined])
  })

  it('升序 [5, null, 3, null, 8]: null 末位, 非 null 升序', () => {
    const arr = [5, null, 3, null, 8]
    arr.sort((a, b) => sortCompare(a, b, 1))
    expect(arr).toEqual([3, 5, 8, null, null])
  })

  it('降序 [5, null, 3, null, 8]: null 首位 (原行为), 非 null 降序', () => {
    const arr = [5, null, 3, null, 8]
    arr.sort((a, b) => sortCompare(a, b, -1))
    expect(arr).toEqual([null, null, 8, 5, 3])
  })
})

describe('tableSort.sortCompare — 数字 / 字符串', () => {
  it('数字 vs 数字: 升序 (a - b)', () => {
    expect(sortCompare(3, 5, 1)).toBeLessThan(0)
    expect(sortCompare(3, 5, -1)).toBeGreaterThan(0)
    expect(sortCompare(5, 5, 1)).toBe(0)
  })

  it('字符串 vs 字符串: localeCompare', () => {
    expect(sortCompare('apple', 'banana', 1)).toBeLessThan(0)
    expect(sortCompare('apple', 'banana', -1)).toBeGreaterThan(0)
  })
})

describe('tableSort.getSortValue', () => {
  const row = { stock_code: '000001', vol: 100, day_pnl: 200 }

  it('列定义有 sortFn → 优先用 sortFn(row)', () => {
    const col = { key: 'market_value', sortFn: (r) => r.vol * 10 }
    expect(getSortValue(row, col)).toBe(1000)
  })

  it('列定义无 sortFn → fallback row[col.key]', () => {
    const col = { key: 'vol' }
    expect(getSortValue(row, col)).toBe(100)
  })

  it('sortFn 返回 null 也正常 (用于"行情未到 → null"场景)', () => {
    const col = { key: 'market_value', sortFn: () => null }
    expect(getSortValue(row, col)).toBeNull()
  })

  it('col.key 缺省时返回 undefined (防御性)', () => {
    expect(getSortValue(row, {})).toBeUndefined()
  })

  it('col 缺省时返回 undefined', () => {
    expect(getSortValue(row, null)).toBeUndefined()
  })

  it('row 中无该字段时返回 undefined (而非抛错)', () => {
    const col = { key: 'missing' }
    expect(getSortValue(row, col)).toBeUndefined()
  })
})

describe('tableSort — 端到端排序 (REQ-FE-540 验收场景)', () => {
  // 模拟 HoldingsPanel 按 market_value / day_pnl / profit / return_rate 排序
  const positions = [
    { stock_code: 'A', vol: 100, last_price: 10, day_pnl: -50, cost_price: 9 },
    { stock_code: 'B', vol: 200, last_price: null, day_pnl: 100, cost_price: 8 }, // 行情未到
    { stock_code: 'C', vol: 50,  last_price: 20, day_pnl: 0,   cost_price: 15 },
  ]

  it('按市值 (sortFn) 升序: A(1000)/C(1000) 同值稳定, B(null) 末位', () => {
    const col = {
      key: 'market_value',
      sortFn: (r) => (r.last_price == null ? null : r.vol * r.last_price),
    }
    const sorted = [...positions].sort((a, b) =>
      sortCompare(getSortValue(a, col), getSortValue(b, col), 1),
    )
    // A=1000, C=1000 同分稳定排序 → [A, C], B=null 升序末位
    expect(sorted).toEqual([
      { stock_code: 'A', vol: 100, last_price: 10, day_pnl: -50, cost_price: 9 },
      { stock_code: 'C', vol: 50,  last_price: 20, day_pnl: 0,   cost_price: 15 },
      { stock_code: 'B', vol: 200, last_price: null, day_pnl: 100, cost_price: 8 },
    ])
  })

  it('按市值 (sortFn) 降序: B(null) 首位 (原行为), A(1000)/C(1000) 同值稳定', () => {
    const col = {
      key: 'market_value',
      sortFn: (r) => (r.last_price == null ? null : r.vol * r.last_price),
    }
    const sorted = [...positions].sort((a, b) =>
      sortCompare(getSortValue(a, col), getSortValue(b, col), -1),
    )
    // null 在降序时排首位 (原 DataTableView 行为)
    expect(sorted[0].stock_code).toBe('B')
    expect(sorted.slice(1).map((r) => r.stock_code)).toEqual(['A', 'C'])
  })

  it('按当日盈亏 (row[prop]) 升序: A(-50) < C(0) < B(100)', () => {
    const col = { key: 'day_pnl' }
    const sorted = [...positions].sort((a, b) =>
      sortCompare(getSortValue(a, col), getSortValue(b, col), 1),
    )
    expect(sorted.map((r) => r.stock_code)).toEqual(['A', 'C', 'B'])
  })

  it('按当日盈亏 (row[prop]) 降序: B(100) > C(0) > A(-50)', () => {
    const col = { key: 'day_pnl' }
    const sorted = [...positions].sort((a, b) =>
      sortCompare(getSortValue(a, col), getSortValue(b, col), -1),
    )
    expect(sorted.map((r) => r.stock_code)).toEqual(['B', 'C', 'A'])
  })

  it('按收益率 (sortFn) 升序: A(0.111) < C(0.333) < B(null 末位)', () => {
    const col = {
      key: 'return_rate',
      sortFn: (r) => {
        if (r.last_price == null) return null
        if (r.cost_price === 0) return null
        return (r.last_price - r.cost_price) / r.cost_price
      },
    }
    const sorted = [...positions].sort((a, b) =>
      sortCompare(getSortValue(a, col), getSortValue(b, col), 1),
    )
    expect(sorted[0].stock_code).toBe('A')
    expect(sorted[1].stock_code).toBe('C')
    expect(sorted[sorted.length - 1].stock_code).toBe('B')
  })

  it('按浮动盈亏 (sortFn) 升序: A(100元) < C(250元) < B(null 末位)', () => {
    const col = {
      key: 'profit',
      sortFn: (r) => {
        if (r.last_price == null) return null
        return (r.last_price - r.cost_price) * r.vol
      },
    }
    // A: (10-9)*100 = 100; C: (20-15)*50 = 250; B: null
    // 升序: A < C < B
    const sorted = [...positions].sort((a, b) =>
      sortCompare(getSortValue(a, col), getSortValue(b, col), 1),
    )
    expect(sorted[0].stock_code).toBe('A')
    expect(sorted[1].stock_code).toBe('C')
    expect(sorted[sorted.length - 1].stock_code).toBe('B')
  })
})

describe('tableSort — 向后兼容 (旧调用方无 sortFn)', () => {
  const data = [
    { name: 'banana', score: 5 },
    { name: 'apple', score: 10 },
    { name: 'cherry', score: 1 },
  ]

  it('列定义无 sortFn: 按 row[col.key] 排序 (与改动前一致)', () => {
    const col = { key: 'score' }
    const sorted = [...data].sort((a, b) =>
      sortCompare(getSortValue(a, col), getSortValue(b, col), -1),
    )
    expect(sorted.map((r) => r.name)).toEqual(['apple', 'banana', 'cherry'])
  })

  it('列定义无 sortFn + 字符串字段: localeCompare', () => {
    const col = { key: 'name' }
    const sorted = [...data].sort((a, b) =>
      sortCompare(getSortValue(a, col), getSortValue(b, col), 1),
    )
    expect(sorted.map((r) => r.name)).toEqual(['apple', 'banana', 'cherry'])
  })
})
