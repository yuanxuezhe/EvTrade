/**
 * trdDateFilter.js —— filterByTrdDate 单元测试
 * 覆盖: exact / exact 优先级 / start-end 范围 / 仅 start / 仅 end / 空 range / 缺省 / 空数组 / 不修改原数组
 */
import { describe, it, expect } from 'vitest'
import { filterByTrdDate } from '../../src/utils/trdDateFilter'

const items = [
  { trd_date: '20260628', id: 1 },
  { trd_date: '20260630', id: 2 },
  { trd_date: '20260701', id: 3 },
  { trd_date: '20260705', id: 4 },
]

describe('filterByTrdDate', () => {
  it('exact 模式: 仅返回精确匹配的日期', () => {
    expect(filterByTrdDate(items, { exact: '20260630' })).toEqual([
      { trd_date: '20260630', id: 2 },
    ])
  })

  it('exact 优先级高于 start/end', () => {
    expect(
      filterByTrdDate(items, { exact: '20260630', start: '20260701', end: '20260710' })
    ).toEqual([{ trd_date: '20260630', id: 2 }])
  })

  it('start/end 范围 (含端点)', () => {
    expect(filterByTrdDate(items, { start: '20260630', end: '20260701' })).toEqual([
      { trd_date: '20260630', id: 2 },
      { trd_date: '20260701', id: 3 },
    ])
  })

  it('仅 start_date: 无下界', () => {
    expect(filterByTrdDate(items, { start: '20260701' })).toEqual([
      { trd_date: '20260701', id: 3 },
      { trd_date: '20260705', id: 4 },
    ])
  })

  it('仅 end_date: 无上界', () => {
    expect(filterByTrdDate(items, { end: '20260630' })).toEqual([
      { trd_date: '20260628', id: 1 },
      { trd_date: '20260630', id: 2 },
    ])
  })

  it('空 range = 不过滤 (返回副本)', () => {
    const result = filterByTrdDate(items, {})
    expect(result).toEqual(items)
    expect(result).not.toBe(items)  // 不污染原引用
  })

  it('缺省 range = 不过滤', () => {
    expect(filterByTrdDate(items)).toEqual(items)
  })

  it('空数组', () => {
    expect(filterByTrdDate([], { exact: '20260630' })).toEqual([])
  })

  it('不修改入参数组', () => {
    const orig = [...items]
    filterByTrdDate(items, { exact: '20260630' })
    expect(items).toEqual(orig)
  })
})
