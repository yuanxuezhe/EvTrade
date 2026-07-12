<!--
  StockCodeAutocomplete.vue — 股票代码/名称/拼音首字母 autocomplete 控件 (v25/v26/v27)

  数据源: useStocksStore.cache (全量 5529, 内存, 跨页面共享)
  筛选: stock_code 前缀 OR stock_name 包含 OR short_name 前缀
  排序: code 前缀 (score=3) > short_name 前缀 (score=2) > name 包含 (score=1)

  v27 重构: 左右拆分
    - 左 (50%): el-autocomplete 股票代码 (可输入 + autocomplete 触发候选)
    - 右 (50%): disabled el-input 证券名称 (只读, 选中候选后自动加载)
    - 改代码 → 名称清空 → 重新选 → 名称重新加载

  Props:
    - modelValue  (string): v-model stock_code (only 600519.SH, 不含名称)
    - placeholder (string): 占位符
    - disabled    (boolean): 是否禁用
    - clearable   (boolean): 可清空
    - size        (string): 'default' | 'small' | 'large'

  Emits:
    - update:modelValue (string): stock_code 输入变化
    - select (stock): 用户从候选中选中, item 是完整 stock 对象
    - blur (): 失焦

  使用场景 (v26 通用化):
    - Trade.vue (交易下单)         : modelValue = stock_code, stock_name 通过 @select 写 form.stock_name
    - T0Trade / Strategy (策略下单): 同上
    - AdminStockConfig (admin)     : modelValue = stock_code, 编辑 PATCH 用
-->
<template>
  <div class="sca-wrapper">
    <!-- 左: 代码输入 (el-autocomplete) -->
    <el-autocomplete
      :model-value="modelValue"
      :placeholder="placeholder || '代码'"
      :disabled="disabled"
      :clearable="clearable"
      :size="size"
      :trigger-on-focus="triggerOnFocus"
      :fetch-suggestions="querySearch"
      @select="onSelectItem"
      @update:model-value="onUpdate"
      @blur="$emit('blur')"
      value-key="stock_code"
      class="sca-code-input"
    >
      <template #default="{ item }">
        <div class="sca-row">
          <span class="sca-code text-mono">{{ item.stock_code }}</span>
          <span class="sca-name">{{ item.stock_name }}</span>
          <span v-if="item.short_name" class="sca-short">[{{ item.short_name }}]</span>
        </div>
      </template>
    </el-autocomplete>

    <!-- 右: 证券名称 (disabled, 只读) -->
    <el-input
      :model-value="displayName"
      :placeholder="namePlaceholder"
      :size="size"
      disabled
      class="sca-name-input"
    />
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import { useStocksStore } from '../stores/stocks'

const props = defineProps({
  modelValue: { type: String, default: '' },
  placeholder: { type: String, default: '' },
  namePlaceholder: { type: String, default: '请选择股票' },
  disabled: { type: Boolean, default: false },
  clearable: { type: Boolean, default: true },
  triggerOnFocus: { type: Boolean, default: false },
  size: { type: String, default: 'default' }
})

const emit = defineEmits(['update:modelValue', 'select', 'blur'])

const store = useStocksStore()

// v27: 右半部分证券名称 (内部 state, 不参与 v-model)
const displayName = ref('')

// 缓存 loadCache promise(避免并发触发)
let cacheLoadPromise = null
async function ensureCache() {
  if (store.cacheLoaded) return
  if (cacheLoadPromise) return cacheLoadPromise
  cacheLoadPromise = store.loadCache().catch((e) => {
    cacheLoadPromise = null
    throw e
  })
  return cacheLoadPromise
}

/**
 * el-autocomplete fetch-suggestions
 */
async function querySearch(queryString, cb) {
  try {
    await ensureCache()
  } catch (e) {
    cb([])
    return
  }
  const results = store.searchCache(queryString, 50)
  cb(results)
}

// v27: el-autocomplete 选中候选时,emit 顺序是:
//   emit('input', item.value)             # 我们没用 v-model:input
//   emit('update:modelValue', item.value) # 触发父组件 v-model = stock_code
//   emit('select', item)                  # 通知父组件 item 选了什么
// 名称同步在 watch props.modelValue 里完成(去 cache 查),不依赖 onSelect 函数
function onSelectItem(item) {
  // 透传 select 给父组件 (OrderForm 用 item.stock_name 写 form.stock_name)
  if (item && item.stock_code) emit('select', item)
}
function onUpdate(val) {
  // v27: modelValue 是纯 stock_code (不带空格和名称)
  emit('update:modelValue', val)
  // 不在这里清空 displayName, watch props.modelValue 处理
}

// v27: 监听 props.modelValue 同步 displayName
//   element-plus el-autocomplete 选中候选时先 emit update:modelValue(stock_code),
//   props.modelValue 变化 → 我们去 cache 找匹配项,填充名称;找不到则清空 (强制重选)
watch(() => props.modelValue, (newVal) => {
  if (!newVal) {
    displayName.value = ''
    return
  }
  const matched = store.cache.find((s) => s.stock_code === newVal)
  displayName.value = matched ? (matched.stock_name || '') : ''
})

// v27: 父组件可能传 defaultStockCode, 此时 cache 可能还没加载,
//   加载完后若 modelValue 命中 cache 自动填充名称
watch(() => store.cacheLoaded, (loaded) => {
  if (loaded && props.modelValue) {
    const matched = store.cache.find((s) => s.stock_code === props.modelValue)
    if (matched) displayName.value = matched.stock_name || ''
  }
}, { immediate: true })
</script>

<style scoped>
.sca-wrapper {
  display: flex;
  width: 100%;
  gap: 8px;
  align-items: center;
}

.sca-code-input {
  flex: 1;
  min-width: 0;
}

.sca-name-input {
  flex: 1;
  min-width: 0;
}

/* disabled 输入框用次要文字色让"未选"状态明显 */
.sca-name-input :deep(.el-input__inner) {
  color: var(--el-text-color-regular, #606266);
  background-color: var(--el-fill-color-light, #f5f7fa);
}

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