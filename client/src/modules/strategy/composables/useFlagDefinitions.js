/**
 * useFlagDefinitions.js — flag 注册表组合式（task 11.3）
 *
 * 行为：
 * - 首次调用 load() → store.loadFlagDefinitions()
 * - 后续读 ref(flagDefinitions) 响应式缓存
 * - 提供 groupByCategory() 按 category 分组（FlagPicker 用）
 * - 提供 findByCode(code) 反查
 *
 * 不持有本地 Map，统一走 Pinia store（多组件共享缓存）
 */
import { computed } from 'vue'
import { useStrategyStore } from '../../../stores/strategy'

export function useFlagDefinitions() {
  const store = useStrategyStore()

  /** 触发懒加载（首次 mount 调一次） */
  async function load(force = false) {
    if (store.flagDefinitions.length === 0 || force) {
      await store.loadFlagDefinitions()
    }
    return store.flagDefinitions
  }

  const flags = computed(() => store.flagDefinitions)

  /** 按 category 分组（保留 FLAG_REGISTRY 注册顺序） */
  const groupByCategory = computed(() => {
    const out = {}
    for (const f of store.flagDefinitions) {
      if (!out[f.category]) out[f.category] = []
      out[f.category].push(f)
    }
    return out
  })

  function findByCode(code) {
    return store.flagDefinitions.find((f) => f.code === code) || null
  }

  return { flags, groupByCategory, load, findByCode }
}