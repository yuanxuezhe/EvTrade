/**
 * useQuoteSubscription.js 测试 (REQ-FE-538, 7 用例)
 *
 * 覆盖 SPEC §6.1 验收清单:
 *   - 立即订阅 (immediate + flush:post)
 *   - codes 变化时 diff subscribe(added) + unsubscribe(removed)
 *   - onBeforeUnmount 自动 unsubscribe
 *   - 跨页面订阅隔离 (订阅同一 code 不互相影响 unsubscribe)
 *   - 空数组边界
 *   - 去重 + 过滤 falsy
 *   - ref 直接传入 (不只支持 getter)
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { ref, onBeforeUnmount, nextTick, defineComponent, h } from 'vue'
import { mount } from '@vue/test-utils'

// 真实 quote store + 真实 composable (不 mock)
import { useQuoteStore } from '@/stores/quote'
import { useQuoteSubscription } from '@/composables/useQuoteSubscription'

// mock @/api 避免 quoteStore 内部 http.post(/quote/snapshots) 真实网络请求
vi.mock('@/api', () => ({
  http: { post: vi.fn().mockResolvedValue({ data: { snapshots: {} } }) },
}))

async function flush() {
  await nextTick()
  await new Promise((r) => setTimeout(r, 0))
}

describe('useQuoteSubscription (REQ-FE-538)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('挂载时立即订阅 codes (immediate + flush:post)', async () => {
    const wrapper = mount(
      defineComponent({
        setup() {
          useQuoteSubscription(() => ['600030.SH', '000001.SZ'])
          return () => h('div')
        },
      })
    )
    await flush()
    const q = useQuoteStore()
    expect(q.subscribedSet.has('600030.SH')).toBe(true)
    expect(q.subscribedSet.has('000001.SZ')).toBe(true)
    wrapper.unmount()
  })

  it('codes 变化时 diff: subscribe(added) + unsubscribe(removed)', async () => {
    const codes = ref(['600030.SH', '000001.SZ'])
    const wrapper = mount(
      defineComponent({
        setup() {
          useQuoteSubscription(() => codes.value)
          return () => h('div')
        },
      })
    )
    await flush()
    const q = useQuoteStore()
    expect(q.subscribedSet.size).toBe(2)

    // 切换 codes: 移除 600030, 新增 000002
    codes.value = ['000001.SZ', '000002.SZ']
    await flush()

    expect(q.subscribedSet.has('600030.SH')).toBe(false)  // removed
    expect(q.subscribedSet.has('000001.SZ')).toBe(true)   // 保持
    expect(q.subscribedSet.has('000002.SZ')).toBe(true)   // added
    expect(q.subscribedSet.size).toBe(2)
    wrapper.unmount()
  })

  it('组件 unmount 时自动 unsubscribe (无幽灵订阅)', async () => {
    const wrapper = mount(
      defineComponent({
        setup() {
          useQuoteSubscription(() => ['600030.SH', '000001.SZ'])
          return () => h('div')
        },
      })
    )
    await flush()
    const q = useQuoteStore()
    expect(q.subscribedSet.size).toBe(2)

    wrapper.unmount()
    await flush()

    expect(q.subscribedSet.has('600030.SH')).toBe(false)
    expect(q.subscribedSet.has('000001.SZ')).toBe(false)
    expect(q.subscribedSet.size).toBe(0)
  })

  it('跨页面订阅隔离: A 卸载不影响 B 的订阅', async () => {
    const q = useQuoteStore()
    // 页面 A 订阅 ['600030.SH']
    const wrapperA = mount(
      defineComponent({
        setup() {
          useQuoteSubscription(() => ['600030.SH'])
          return () => h('div')
        },
      })
    )
    // 页面 B 订阅 ['600030.SH', '600519.SH']
    const wrapperB = mount(
      defineComponent({
        setup() {
          useQuoteSubscription(() => ['600030.SH', '600519.SH'])
          return () => h('div')
        },
      })
    )
    await flush()
    expect(q.subscribedSet.size).toBe(2)  // 600030 + 600519

    // A 卸载: 600030 应仍被 B 订阅 (依赖 quoteStore.subscribedSet 全局去重)
    wrapperA.unmount()
    await flush()

    expect(q.subscribedSet.has('600030.SH')).toBe(true)   // B 仍订阅
    expect(q.subscribedSet.has('600519.SH')).toBe(true)   // B 仍订阅
    expect(q.subscribedSet.size).toBe(2)
    wrapperB.unmount()
  })

  it('空 codes 数组边界: 不 subscribe, unmount 不 unsubscribe', async () => {
    const wrapper = mount(
      defineComponent({
        setup() {
          useQuoteSubscription(() => [])
          return () => h('div')
        },
      })
    )
    await flush()
    const q = useQuoteStore()
    expect(q.subscribedSet.size).toBe(0)

    wrapper.unmount()  // 不应抛错, 不应误 unsubscribe
    await flush()
    expect(q.subscribedSet.size).toBe(0)
  })

  it('去重 + 过滤 falsy: 同 code 多次只订阅 1 次, null/空串跳过', async () => {
    const wrapper = mount(
      defineComponent({
        setup() {
          useQuoteSubscription(() => [
            '600030.SH', '600030.SH',  // 重复
            null, undefined, '',        // falsy
            '000001.SZ',
          ])
          return () => h('div')
        },
      })
    )
    await flush()
    const q = useQuoteStore()
    expect(q.subscribedSet.size).toBe(2)
    expect(q.subscribedSet.has('600030.SH')).toBe(true)
    expect(q.subscribedSet.has('000001.SZ')).toBe(true)
    wrapper.unmount()
  })

  it('支持直接传 ref (不只支持 getter)', async () => {
    const codesRef = ref(['600030.SH'])
    const wrapper = mount(
      defineComponent({
        setup() {
          useQuoteSubscription(codesRef)
          return () => h('div')
        },
      })
    )
    await flush()
    const q = useQuoteStore()
    expect(q.subscribedSet.has('600030.SH')).toBe(true)

    codesRef.value = ['600030.SH', '000001.SZ']
    await flush()
    expect(q.subscribedSet.has('000001.SZ')).toBe(true)
    wrapper.unmount()
  })
})
