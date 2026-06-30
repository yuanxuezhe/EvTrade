/**
 * date.js — 日期字符串工具
 *
 * shiftDateStr(yyyymmdd, deltaDays): 在 YYYYMMDD 字符串上加减天数
 *   - 输入输出均为 8 位字符串（不含分隔符）
 *   - 字典序 = 时间序，调用方比较时无需 parse
 *   - 格式非法抛 Error
 */
export function shiftDateStr(yyyymmdd, deltaDays) {
  if (!/^\d{8}$/.test(yyyymmdd)) {
    throw new Error(`shiftDateStr: invalid date format "${yyyymmdd}", expected YYYYMMDD`)
  }
  const y = Number(yyyymmdd.slice(0, 4))
  const m = Number(yyyymmdd.slice(4, 6))
  const d = Number(yyyymmdd.slice(6, 8))
  const dt = new Date(Date.UTC(y, m - 1, d))
  dt.setUTCDate(dt.getUTCDate() + deltaDays)
  const yy = dt.getUTCFullYear()
  const mm = String(dt.getUTCMonth() + 1).padStart(2, '0')
  const dd = String(dt.getUTCDate()).padStart(2, '0')
  return `${yy}${mm}${dd}`
}
