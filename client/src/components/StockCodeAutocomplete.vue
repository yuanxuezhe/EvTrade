<!--
  StockCodeAutocomplete.vue — 股票代码/名称/拼音首字母 autocomplete 输入组件 (v25)

  数据源: useStocksStore.cache (全量 5529, 内存)
  筛选: stock_code 前缀 OR stock_name 包含 OR short_name 前缀
  排序: code 前缀 (score=3) > short_name 前缀 (score=2) > name 包含 (score=1)

  Props:
    - modelValue (string): v-model stock_code
    - placeholder (string): 占位符
    - disabled (boolean): 是否禁用
    - clearable (boolean): 可清空,默认 true
    - triggerOnFocus (boolean): focus 时立即展示所有 cache,默认 false
    - size (string): 'default' | 'small' | 'large'

  Emits:
    - update:modelValue (string): 输入变化 (即使无候选)
    - select (stock): 用户从候选中选中 (仅当选中真实存在的 stock)
    - blur (): 失焦

  设计要点:
    - 无效输入(无候选)时不 emit select,只 emit update:modelValue
    - 必须命中 cache 中真实存在的 stock_code 才允许确认
    - 候选列表显示 stock_code + stock_name [+ short_name]
    - cache 未加载时(input 触发),自动触发 loadCache
-->
<template>
  <el-autocomplete
    :model-value="modelValue"
    :placeholder="placeholder || '输入代码 / 名称 / 首字母'"
    :disabled="disabled"
    :clearable="clearable"
    :size="size"
    :trigger-on-focus="triggerOnFocus"
    :fetch-suggestions="querySearch"
    @select="onSelect"
    @update:model-value="onUpdate"
    @blur="$emit('blur')"
    value-key="stock_code"
    style="width: 100%"
  >
    <template #default="{ item }">
      <div class="sca-row">
        <span class="sca-code text-mono">{{ item.stock_code }}</span>
        <span class="sca-name">{{ item.stock_name }}</span>
        <span v-if="item.short_name" class="sca-short">[{{ item.short_name }}]</span>
      </div>
    </template>
  </el-autocomplete>
</template>

<script setup>
import { ref, watch } from 'vue'
import { useStocksStore } from '../stores/stocks'

const props = defineProps({
  modelValue: { type: String, default: '' },
  placeholder: { type: String, default: '' },
  disabled: { type: Boolean, default: false },
  clearable: { type: Boolean, default: true },
  triggerOnFocus: { type: Boolean, default: false },
  size: { type: String, default: 'default' }
})

const emit = defineEmits(['update:modelValue', 'select', 'blur'])

const store = useStocksStore()

// 缓存 loadCache promise(避免并发触发)
let cacheLoadPromise = null
async function ensureCache() {
  if (store.cacheLoaded) return
  if (cacheLoadPromise) return cacheLoadPromise
  cacheLoadPromise = store.loadCache().catch((e) => {
    cacheLoadPromise = null  // 下次允许重试
    throw e
  })
  return cacheLoadPromise
}

/**
 * el-autocomplete fetch-suggestions
 * @param {string} queryString
 * @param {function} cb 回调函数,接收候选数组
 */
async function querySearch(queryString, cb) {
  try {
    await ensureCache()
  } catch (e) {
    // cache 加载失败:返回空,允许用户继续输入
    cb([])
    return
  }
  const results = store.searchCache(queryString, 50)
  cb(results)
}

function onSelect(item) {
  // 选中真实存在的 stock 才 emit select
  if (item && item.stock_code) {
    emit('update:modelValue', item.stock_code)
    emit('select', item)
  }
}

function onUpdate(val) {
  emit('update:modelValue', val)
  // 注意:不在这里 emit select(用户可能只是输入,不一定选中了)
}

// 当外部 v-model 改变时(比如 PATCH 后刷新),确保 cache 里存在
watch(() => props.modelValue, async (newVal) => {
  if (newVal && store.cacheLoaded) {
    // 已在 cache 中 → 无操作
    const exists = store.cache.find((s) => s.stock_code === newVal)
    if (!exists) {
      // 罕见:外部设了一个 cache 里没有的 code(如 PATCH 失败 rollback)
      // → 重新拉 cache
      await store.loadCache()
    }
  }
})
</script>

<style scoped>
.sca-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}
.sca-code {
  color: var(--el-color-primary, #409eff);
  font-weight: 600;
  min-width: 90px;
}
.sca-name {
  flex: 1;
  color: var(--el-text-color-primary, #303133);
}
.sca-short {
  color: var(--el-text-color-secondary, #909399);
  font-family: var(--font-mono, 'JetBrains Mono', 'Consolas', monospace);
  font-size: 11px;
}
.text-mono {
  font-family: var(--font-mono, 'JetBrains Mono', 'Consolas', monospace);
}
</style>