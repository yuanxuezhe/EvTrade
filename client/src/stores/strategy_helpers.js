/**
 * strategy_helpers.js — strategy store 无状态 helpers（task 10 拆文件以保 ≤250 行）
 *
 * 提供：
 * - createPendingTracker() — pending Set + _isPending/_setPending（响应式包装）
 * - upsertStrategy(list, strategy) — 按 id in-place 替换或追加
 * - removeStrategy(list, id) — 按 id 移除
 * - patchAuditCache(cache, id, trdDate, audit?) — 写或追加 audit 缓存
 *
 * 纯函数，无 store 依赖。可单测。
 */

export function createPendingTracker() {
  const pending = { value: new Set() }
  function isPending(key) {
    return pending.value.has(key)
  }
  function setPending(key, on) {
    if (on) pending.value.add(key)
    else pending.value.delete(key)
    // 触发响应式（Set 引用变化才会被 Vue 追踪）
    pending.value = new Set(pending.value)
  }
  return { pending, isPending, setPending }
}

/**
 * 按 id in-place 替换（找到）或追加（未找到）。返回是否替换。
 * @param {Array<Object>} list 响应式 ref 内部数组
 * @param {Object} strategy 必须有 .id
 */
export function upsertStrategy(list, strategy) {
  if (!strategy || strategy.id == null) return false
  const idx = list.findIndex((s) => s.id === strategy.id)
  if (idx >= 0) {
    list.splice(idx, 1, strategy)
    return true
  }
  list.push(strategy)
  return false
}

/**
 * 按 id 移除；找不到静默。
 */
export function removeStrategy(list, id) {
  const idx = list.findIndex((s) => s.id === id)
  if (idx >= 0) list.splice(idx, 1)
}

/**
 * 写 audit 缓存（按 (id, trdDate) 嵌套）；不传 audit 则初始化空数组。
 * 直接 mutate cache 即可（响应式对象）。
 */
export function setAuditCache(cache, id, trdDate, audits) {
  if (!cache[id]) cache[id] = {}
  cache[id][trdDate] = audits
}

/**
 * 增量推入 audit 列表头部；找不到则初始化。
 */
export function appendAuditCache(cache, id, trdDate, audit) {
  if (!cache[id]) cache[id] = {}
  if (!cache[id][trdDate]) cache[id][trdDate] = []
  cache[id][trdDate] = [audit, ...cache[id][trdDate]]
}

/**
 * 删除整个 strategy 的 audit 缓存（被 deleteStrategy 使用）。
 */
export function clearAuditCache(cache, id) {
  delete cache[id]
}
