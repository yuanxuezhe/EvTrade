/**
 * tableSort.js — DataTableView 客户端排序纯函数 (2026-09-18)
 *
 * 设计目标:
 *   - 把"列定义 → 排序 key" + "两个 key → 大小" 拆成可独立单测的纯函数
 *   - DataTableView 内部 computed 直接复用, 不暴露 computed 给外部
 *
 * 与 DataTableView 关系:
 *   - sortCompare: 内部 sortCompare 1:1 移植 (null 兜底 + 数字/字符串分支)
 *   - getSortValue: 列定义有 sortFn 优先用 sortFn(row), 否则 row[col.key]
 *
 * 用法 (DataTableView 内):
 *   import { sortCompare, getSortValue } from '../utils/tableSort'
 *   [...data].sort((a, b) => sortCompare(getSortValue(a, col), getSortValue(b, col), dir))
 */

/**
 * 两个排序值比较
 *
 * - null/undefined 兜底 (与原 DataTableView 行为 1:1):
 *   - va=null, vb=非null: return dir → null 升序末位 / 降序首位
 *   - va=非null, vb=null: return -dir → 同上 (相对位置)
 *   - va=null, vb=null: 0 (顺序保持)
 * - 数字 vs 数字: (va - vb) * dir
 * - 其他: String(va).localeCompare(String(vb)) * dir
 *
 * @param {*} va - 左值 (可 null/undefined)
 * @param {*} vb - 右值 (可 null/undefined)
 * @param {number} dir - 1 升序 / -1 降序
 * @returns {number} < 0 va < vb; > 0 va > vb; === 0 相等
 */
export function sortCompare(va, vb, dir) {
  if (va == null && vb == null) return 0
  if (va == null) return dir
  if (vb == null) return -dir
  if (typeof va === 'number' && typeof vb === 'number') return (va - vb) * dir
  return String(va).localeCompare(String(vb)) * dir
}

/**
 * 从行 + 列定义派生排序 key
 *
 * - 列定义有 sortFn (function) → 优先用 sortFn(row)
 * - 否则 → row[col.key] (向后兼容老调用方)
 *
 * @param {Object} row - 数据行
 * @param {Object} col - 列定义 { key, sortFn? }
 * @returns {*} 排序 key (可 null/undefined, 由 sortCompare 兜底)
 */
export function getSortValue(row, col) {
  if (col && typeof col.sortFn === 'function') return col.sortFn(row)
  if (col && col.key != null) return row[col.key]
  return undefined
}
