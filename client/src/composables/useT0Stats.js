/**
 * useT0Stats.js — t0Stats 30s TTL 内存缓存 (t0-trade-polish-bundle commit 3)
 *
 * Why:
 *   - T0Trade 首屏 30 持仓 → 30 GET 串行, 大账户"今盈"列普遍 '--'
 *   - ws push (200ms 频率) 即时 invalid 该 stock_code 缓存键
 *   - 30s 折中: 大幅减请求 + push 期间 cache 命中率 ~70%
 *
 * API:
 *   - getStats(code, force=false) → Promise<stats> (hit+fresh 返 cache, 否则 fetch+set)
 *   - loadAll(codes[]) → Promise<{code: stats}> (并行, 复用 getStats 单标的)
 *   - invalidate(code) → 删单个 (ws push 调)
 *   - invalidateAll() → clear all (跨日 / 测试)
 *   - _resetCache() (测试用)
 *
 * change t0-trade-polish-bundle (commit 3)
 */

import { t0StatsApi } from '../api/t0_stats'

const TTL_MS = 30_000

// 模块级 Map (singleton, 跨 useT0Stats() 调用共享缓存)
//   - 设计理由: 同一页面多个 useT0Stats() 实例应共享缓存, 否则退化为无缓存
//   - 测试隔离: useT0Stats._resetCache() 提供显式清空入口
const _cache = new Map()


/**
 * 取单标的 stats (命中 + 新鲜 → 返缓存, 否则 fetch 后 set)
 *
 * @param {string} code — stock_code
 * @param {boolean} [force=false] — true 跳过缓存直接 fetch
 * @returns {Promise<Object|null>}
 */
async function getStats(code, force = false) {
  if (!code) return null
  const hit = _cache.get(code)
  const fresh = hit && !force && (Date.now() - hit.ts < TTL_MS)
  if (fresh) return hit.data
  try {
    const data = await t0StatsApi.get(code, null, true)
    _cache.set(code, { data, ts: Date.now() })
    return data
  } catch (e) {
    console.warn(`[useT0Stats] getStats failed for ${code}:`, e)
    // 错码: 不写缓存 (下次 fetch 仍 miss), 也不 throw (调用方期望 best-effort)
    return null
  }
}


/**
 * 并发加载多个标的 stats (复用 getStats 单标的 → 走缓存 miss → fetch)
 *
 * @param {string[]} codes — stock_code[]
 * @returns {Promise<Object>} { [code]: stats | null }
 */
async function loadAll(codes) {
  const list = Array.isArray(codes) ? codes.filter(Boolean) : []
  if (list.length === 0) return {}
  const results = await Promise.allSettled(list.map((code) => getStats(code)))
  const out = {}
  results.forEach((r, i) => {
    if (r.status === 'fulfilled' && r.value) {
      out[list[i]] = r.value
    }
  })
  return out
}


/**
 * 使单个标的缓存失效 (ws push 时调)
 *
 * @param {string|null|undefined} code — 不传/无效 → 全部失效
 */
function invalidate(code) {
  if (!code) {
    invalidateAll()
    return
  }
  _cache.delete(code)
}


/** 全部失效 (跨日切换 / 测试) */
function invalidateAll() {
  _cache.clear()
}


/** 测试用: 强制清空 (与 invalidateAll 等价, 命名更显眼) */
function _resetCache() {
  _cache.clear()
}


/** 测试用: 当前缓存 size */
function _size() {
  return _cache.size
}


export const useT0Stats = {
  getStats,
  loadAll,
  invalidate,
  invalidateAll,
  _resetCache,
  _size,
  TTL_MS,
}