/**
 * trdDateFilter.js — 按 trd_date 区间筛选委托/成交
 *
 * filterByTrdDate(items, range):
 *   - exact 模式: 精确匹配某日 (优先级最高, 与 start/end 互斥)
 *   - range 模式: [start, end] 含端点 (YYYYMMDD 字符串字典序 = 时间序)
 *   - 空 range: 不过滤, 返回原数组副本
 *   - 不修改入参数组
 */
export function filterByTrdDate(items, range = {}) {
  const { exact, start, end } = range || {}

  if (exact != null) {
    return items.filter((it) => it && it.trd_date === exact)
  }

  if (start == null && end == null) {
    return items.slice()
  }

  return items.filter((it) => {
    if (!it) return false
    const d = it.trd_date
    if (start != null && d < start) return false
    if (end != null && d > end) return false
    return true
  })
}
