/**
 * v32 价格格式化 util
 * - fmtPrice(n): 价格, 最多 4 位小数, 去尾 0
 * - fmtAmount(n): 金额, 最多 2 位小数, 去尾 0
 * 空值/NaN 返 '—'
 */
export function fmtPrice(n) {
  if (n === null || n === undefined || n === '') return '—'
  const num = Number(n)
  if (Number.isNaN(num)) return '—'
  // toFixed(4) 四舍五入到 4 位, parseFloat 去尾 0
  return parseFloat(num.toFixed(4)).toString()
}

export function fmtAmount(n) {
  if (n === null || n === undefined || n === '') return '—'
  const num = Number(n)
  if (Number.isNaN(num)) return '—'
  return parseFloat(num.toFixed(2)).toString()
}
