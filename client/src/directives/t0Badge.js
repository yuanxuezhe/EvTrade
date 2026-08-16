/**
 * directives/t0Badge.js — 全局 Vue 指令 v-t0-badge
 *
 * 用法:
 *   <span v-t0-badge="'600519.SH'">贵州茅台</span>
 *   <td v-t0-badge="row.stock_code">...</td>
 *
 * 行为:
 *   - 从 useStocksStore.cache 查 is_t0_able
 *   - true: 在元素内追加闪电图标胶囊 (非文字), 紧贴右内侧
 *   - false/null: 啥也不做 (no DOM 操作)
 *
 * 样式:
 *   .t0-badge / .t0-badge-icon 定义在全局 main.css (跨 scoped 组件复用)
 *
 * 注意:
 *   - 元素必须能放 inline 内容 (span / td / div)
 *   - 重复调用幂等: 第二次进入不会重复追加 (靠 data-t0-badge 标记)
 *   - cache 未 loaded 时不渲染 (避免误判); 但会挂一个 cache-ready watcher,
 *     缓存加载完成后自动补渲染 (竞态兜底: 行先渲染、cache 后到)
 */
import { watch } from 'vue'
import { useStocksStore } from '../stores/stocks'

export const t0BadgeDirective = {
  mounted(el, binding) {
    renderBadge(el, binding.value)
    ensureBadgeOnCacheReady(el, () => binding.value)
  },
  updated(el, binding) {
    // 仅在 code 变化时重渲染
    const prev = el.dataset.t0Code
    if (prev !== String(binding.value)) {
      // 取消旧的 cache-ready watcher, 重新挂
      cancelCacheWatch(el)
      // 移除旧 badge
      const old = el.querySelector('.t0-badge')
      if (old) old.remove()
      delete el.dataset.t0Badge
      // 关键: 也清掉 t0Code 追踪。否则"t0→非t0→t0"切换时,
      // 非 t0 的 renderBadge 提前 return 没更新 t0Code(仍停留旧值),
      // 切回 t0 后 prev===new 会误判"未变"而跳过重渲染 → badge 丢失
      delete el.dataset.t0Code
      renderBadge(el, binding.value)
      ensureBadgeOnCacheReady(el, () => binding.value)
    }
  },
  unmounted(el) {
    cancelCacheWatch(el)
    const old = el.querySelector('.t0-badge')
    if (old) old.remove()
    delete el.dataset.t0Badge
  },
}

// cache 未 ready 时挂 watcher: cacheLoaded 变 true 即补渲染一次, 然后自毁
function ensureBadgeOnCacheReady(el, getCode) {
  const stocksStore = useStocksStore()
  if (stocksStore.cacheLoaded || el.dataset.t0Badge === '1') return
  const stop = watch(
    () => stocksStore.cacheLoaded,
    (loaded) => {
      if (loaded) {
        renderBadge(el, getCode())
        stop()
        if (el.__t0CacheWatch === stop) delete el.__t0CacheWatch
      }
    }
  )
  el.__t0CacheWatch = stop
}

function cancelCacheWatch(el) {
  if (el.__t0CacheWatch) {
    el.__t0CacheWatch()
    delete el.__t0CacheWatch
  }
}

function renderBadge(el, code) {
  if (!code) return
  const stocksStore = useStocksStore()
  if (!stocksStore.cacheLoaded) return
  const stock = stocksStore.cache?.find?.(s => s.stock_code === code)
  if (!stock?.is_t0_able) return

  // 幂等: 已渲染过跳过
  if (el.dataset.t0Badge === '1') return
  el.dataset.t0Badge = '1'
  el.dataset.t0Code = String(code)

  const span = document.createElement('span')
  span.className = 't0-badge'
  span.title = '支持 T+0'
  // 闪电图标 (Material bolt path) — 表达 T+0 当日回转的速度感, 非文字
  span.innerHTML =
    '<svg class="t0-badge-icon" viewBox="0 0 24 24" aria-hidden="true">' +
    '<path d="M13 2 3 14h6l-1 8 10-12h-6l1-8z"/></svg>'
  el.appendChild(span)
}