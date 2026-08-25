/**
 * useQuoteSubscription — 自动管理 quoteStore.subscribe / unsubscribe 生命周期
 *
 * 用途:
 *   任何展示"实时行情"列表的页面, 把当前可见 codes 传进来,
 *   composable 自动:
 *     - codes 变化时 diff 旧/新, 只 subscribe(added) + unsubscribe(removed)
 *     - 组件 unmount 时自动 unsubscribe(current)
 *
 * 用法:
 *   import { useQuoteSubscription } from '../composables/useQuoteSubscription'
 *
 *   const taskRows = computed(() => t0TasksStore.tasks || [])
 *   useQuoteSubscription(() => taskRows.value.map(r => r.stock_code))
 *
 * ⚠️ **TDZ 警告**: 调用必须在 taskRows / detail 等被引用的 ref/computed
 *    **定义之后**, 否则 setup() 抛 ReferenceError (2026-08-25 实战踩坑).
 *    Vue setup 是同步顺序执行, useQuoteSubscription 内部的 watch(immediate=true)
 *    会在调用瞬间就读 getter, 触发引用.
 *
 * 设计要点:
 *   1. 薄封装 (按你拍板 Q6 候选 A) — 调用方各自管自己 async 竞态 (unmounted flag),
 *      composable 不内置, 不替调用方做决定.
 *   2. flush: 'post' — watch 延迟到 DOM 更新后, 避让 v-for 同时挂载的竞争.
 *   3. diff 算法只动自己的 codes, 不感知跨页面订阅:
 *      - 多页面订阅同一 code 时 unsubscribe 不会误影响其他页面
 *      - 靠 quoteStore.subscribedSet 全局去重 (quote.js L171-198 已实现)
 *   4. 去重 + 过滤 falsy — 同 code 多次出现只订阅 1 次; null/undefined/空串跳过
 *   5. 不传空数组 — codes 为空时直接跳过 (quoteStore.subscribe 内部已 defend,
 *      但 diff 算法看到 lastCodes 空也不会误 unsubscribe)
 *   6. 返回 codes — 方便模板直接用 (computed, 自动去重 + 过滤)
 *
 * 参考:
 *   - StkPoolView.vue L140-241 教科书式订阅模式
 *   - quote.js L171-198 subscribe/unsubscribe 契约
 *   - spec: openspec/specs/frontend/spec.md REQ-FE-538
 */

import { computed, watch, onBeforeUnmount } from 'vue'
import { useQuoteStore } from '../stores/quote'

/**
 * @param {(() => string[] | null | undefined) | import('vue').Ref<string[] | null | undefined>} codesGetter
 *        返回/包含当前要订阅的 stock_code 列表的 getter 或 ref
 * @returns {{ codes: import('vue').ComputedRef<string[]> }}
 *          codes: 去重 + 过滤 falsy 后的当前 codes (computed, 模板可直接用)
 */
export function useQuoteSubscription(codesGetter) {
  const quoteStore = useQuoteStore()

  // 统一包装为 computed: 同时支持 getter () => arr 或 ref (含直接 ref)
  const codes = computed(() => {
    const raw =
      typeof codesGetter === 'function'
        ? codesGetter()
        : codesGetter && 'value' in codesGetter
          ? codesGetter.value
          : codesGetter
    if (!Array.isArray(raw)) return []
    return Array.from(new Set(raw.filter(Boolean)))
  })

  // 记录上次订阅的 codes (Set, 用于 diff)
  let lastCodes = new Set()

  watch(
    codes,
    (curr) => {
      const currSet = new Set(curr)
      // diff: removed = lastCodes - currSet, added = currSet - lastCodes
      const removed = [...lastCodes].filter((c) => !currSet.has(c))
      const added = [...currSet].filter((c) => !lastCodes.has(c))
      // unsubscribe 先做 (避免瞬时空窗期)
      if (removed.length > 0) quoteStore.unsubscribe(removed)
      // subscribe 后做 (added 优先于 removed 的副作用风险 = 0, 跨页面隔离靠 subscribedSet)
      if (added.length > 0) quoteStore.subscribe(added)
      lastCodes = currSet
    },
    { immediate: true, flush: 'post' }
  )

  // 组件卸载时自动 unsubscribe 当前订阅的全部 codes
  onBeforeUnmount(() => {
    if (lastCodes.size > 0) {
      quoteStore.unsubscribe([...lastCodes])
      lastCodes = new Set()
    }
  })

  return { codes }
}
