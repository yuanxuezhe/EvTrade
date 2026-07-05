<!--
  FlagPicker.vue — 多选 flag 选择器（task 11.5）

  Props：
    modelValue - string[]（已选 flag code 列表，v-model）
    exclude    - string[]（互斥 flag code 列表，单独 disabled + 提示）
    dataElPrefix - data-el 前缀（用于测试定位）
  Emits：
    update:modelValue

  行为：
    - 按 category 分组下拉
    - 每行 checkbox + flag name + 简短说明 popover
    - exclude 列表的 flag 渲染为 disabled 状态（regime.match 中会被剔除）
-->
<template>
  <div class="flag-picker" :data-el="dataElPrefix">
    <el-popover
      placement="bottom-start"
      :width="380"
      trigger="click"
      :disabled="disabled"
      :data-el="dataElPrefix + '-popover'"
    >
      <template #reference>
        <el-button
          :disabled="disabled"
          :data-el="dataElPrefix + '-trigger'"
        >
          {{ triggerLabel }}
          <el-icon class="el-icon--right"><ArrowDown /></el-icon>
        </el-button>
      </template>

      <div class="fp-popover">
        <div v-if="loading" class="fp-loading">加载中...</div>
        <template v-else>
          <div
            v-for="(items, category) in groupByCategory"
            :key="category"
            class="fp-category"
          >
            <div class="fp-cat-title">{{ CATEGORY_LABEL[category] || category }}</div>
            <el-checkbox-group
              :model-value="modelValue"
              @update:model-value="onChange"
              :data-el="dataElPrefix + '-group'"
            >
              <el-checkbox
                v-for="f in items"
                :key="f.code"
                :value="f.code"
                :disabled="isExcluded(f.code)"
                class="fp-flag-row"
                :data-el="dataElPrefix + '-flag-' + f.code"
              >
                <span class="fp-flag-name">{{ f.name }}</span>
                <el-tooltip
                  :content="f.description"
                  placement="top"
                  :show-after="200"
                >
                  <el-icon class="fp-help"><InfoFilled /></el-icon>
                </el-tooltip>
                <span v-if="isExcluded(f.code)" class="fp-excluded-hint">（互斥）</span>
              </el-checkbox>
            </el-checkbox-group>
          </div>
        </template>
      </div>
    </el-popover>

    <!-- 已选 tag 预览 -->
    <div class="fp-preview">
      <el-tag
        v-for="code in modelValue"
        :key="code"
        size="small"
        :type="isExcluded(code) ? 'info' : 'primary'"
        :data-el="dataElPrefix + '-tag-' + code"
      >
        {{ displayName(code) }}
      </el-tag>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import { ArrowDown, InfoFilled } from '@element-plus/icons-vue'
import { useFlagDefinitions } from './composables/useFlagDefinitions'

const props = defineProps({
  modelValue: { type: Array, default: () => [] },
  exclude: { type: Array, default: () => [] },
  disabled: { type: Boolean, default: false },
  dataElPrefix: { type: String, default: 'flag-picker' },
})
const emit = defineEmits(['update:modelValue'])

const CATEGORY_LABEL = {
  trend: '趋势类',
  momentum: '动量类',
  volatility: '波动类',
  volume: '量能类',
  structure: '结构类',
}

const { flags, groupByCategory, load, findByCode } = useFlagDefinitions()
const loading = computed(() => flags.value.length === 0)

onMounted(async () => {
  await load()
})

const triggerLabel = computed(() => {
  const n = props.modelValue.length
  if (n === 0) return '选择 flag'
  return `已选 ${n} 项`
})

function isExcluded(code) {
  return props.exclude.includes(code)
}

function displayName(code) {
  return findByCode(code)?.name || code
}

function onChange(next) {
  emit('update:modelValue', Array.isArray(next) ? next : [])
}
</script>

<style scoped>
.flag-picker {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
}
.fp-popover {
  max-height: 320px;
  overflow-y: auto;
}
.fp-loading {
  text-align: center;
  color: var(--text-placeholder);
  padding: var(--space-3);
}
.fp-category {
  margin-bottom: var(--space-3);
}
.fp-cat-title {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: var(--space-2);
  letter-spacing: 0.5px;
}
.fp-flag-row {
  display: flex !important;
  align-items: center;
  margin-bottom: var(--space-2);
}
.fp-flag-name {
  margin-left: var(--space-1);
}
.fp-help {
  margin-left: var(--space-1);
  color: var(--text-placeholder);
  cursor: help;
}
.fp-excluded-hint {
  margin-left: var(--space-2);
  color: var(--text-placeholder);
  font-size: 11px;
}
.fp-preview {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-1);
}
</style>