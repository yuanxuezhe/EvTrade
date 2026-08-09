/**
 * date.js —— shiftDateStr 单元测试
 * 覆盖: 同月内/跨月/跨年/闰年/正数/delta=0/格式非法
 */
import { describe, it, expect } from 'vitest'
import { shiftDateStr } from '@/utils/date'

describe('shiftDateStr', () => {
  it('同月内 N 天前', () => {
    expect(shiftDateStr('20260630', -5)).toBe('20260625')
  })

  it('跨月', () => {
    expect(shiftDateStr('20260603', -5)).toBe('20260529')
  })

  it('跨年', () => {
    expect(shiftDateStr('20260103', -5)).toBe('20251229')
  })

  it('闰年 2 月', () => {
    // 2024 是闰年
    expect(shiftDateStr('20240301', -1)).toBe('20240229')
    // 2025 非闰年
    expect(shiftDateStr('20250301', -1)).toBe('20250228')
  })

  it('正数向后移', () => {
    expect(shiftDateStr('20260630', 1)).toBe('20260701')
  })

  it('delta=0 返回原值', () => {
    expect(shiftDateStr('20260630', 0)).toBe('20260630')
  })

  it('格式非法抛错', () => {
    expect(() => shiftDateStr('2026-06-30', -1)).toThrow()
    expect(() => shiftDateStr('abc', -1)).toThrow()
  })
})
