<!--
  RegimeEditor.vue — 单 regime 编辑器（task 11.6）

  Props：
    modelValue - 单 regime 对象（id / name / priority / required_flags /
                              exclude_flags / base_volume / clear_position / enabled / grids）
    disabled   - 整体禁用
    dataElPrefix - data-el 前缀
  Emits：
    update:modelValue
    remove
    addGrid - 新增 grid（携带一个空白 grid 对象）

  含 FlagPicker（required_flags + exclude_flags）+ GridEditor 列表
-->
<template>
  <div class="regime-editor" :data-el="dataElPrefix">
    <div class="re-header">
      <div class="re-title-row">
        <el-input
          :model-value="modelValue.name"
          @update:model-value="patch('name', $event)"
          placeholder="regime 名称（例：多头突破 / 空头修复）"
          class="re-name"
          :disabled="disabled"
          data-el="regime-name"
        />
        <el-input-number
          :model-value="modelValue.priority"
          @update:model-value="patch('priority', $event)"
          :min="0"
          :max="9999"
          controls-position="right"
          class="re-priority"
          :disabled="disabled"
          data-el="regime-priority"
        />
        <el-switch
          :model-value="modelValue.enabled !== false"
          @update:model-value="patch('enabled', $event)"
          active-text="启用"
          inactive-text="停用"
          :disabled="disabled"
          data-el="regime-enabled"
        />
        <el-button
          link
          type="danger"
          :disabled="disabled"
          @click="emit('remove')"
          data-el="regime-remove"
        >
          <el-icon><Delete /></el-icon> 删除
        </el-button>
      </div>

      <div class="re-flags-row">
        <span class="re-flags-label">需要 flag：</span>
        <FlagPicker
          :model-value="modelValue.required_flags"
          @update:model-value="patch('required_flags', $event)"
          :exclude="modelValue.exclude_flags"
          :disabled="disabled"
          :data-el-prefix="dataElPrefix + '-required'"
        />
      </div>

      <div class="re-flags-row">
        <span class="re-flags-label">排除 flag：</span>
        <FlagPicker
          :model-value="modelValue.exclude_flags"
          @update:model-value="patch('exclude_flags', $event)"
          :exclude="modelValue.required_flags"
          :disabled="disabled"
          :data-el-prefix="dataElPrefix + '-exclude'"
        />
      </div>

      <div class="re-config-row">
        <el-form-item label="基础量覆盖" label-width="92px" class="re-base-vol">
          <el-input-number
            :model-value="modelValue.base_volume ?? null"
            @update:model-value="patch('base_volume', $event === undefined ? null : $event)"
            :step="100"
            :min="0"
            :max="999999"
            placeholder="（默认使用策略级）"
            :disabled="disabled"
            controls-position="right"
            data-el="regime-base-volume"
          />
        </el-form-item>
        <el-form-item label="触发清仓" label-width="84px" class="re-clear">
          <el-switch
            :model-value="modelValue.clear_position === true"
            @update:model-value="patch('clear_position', $event)"
            :disabled="disabled"
            data-el="regime-clear-position"
          />
          <span class="re-hint">匹配时先清仓再触发 grid</span>
        </el-form-item>
      </div>
    </div>

    <div class="re-grids-section">
      <div class="re-grids-header">
        <span class="re-grids-title">网格列表（{{ grids.length }}）</span>
        <el-button
          size="small"
          type="primary"
          :disabled="disabled"
          @click="emit('addGrid')"
          data-el="regime-add-grid"
        >
          <el-icon><Plus /></el-icon> 新增 grid
        </el-button>
      </div>
      <GridEditor
        v-for="(g, idx) in grids"
        :key="g.id || `new-${idx}`"
        :model-value="g"
        @update:model-value="updateGrid(idx, $event)"
        @remove="removeGrid(idx)"
        :disabled="disabled"
      />
      <el-empty v-if="grids.length === 0" description="暂无 grid" :image-size="60" />
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Delete, Plus } from '@element-plus/icons-vue'
import FlagPicker from './FlagPicker.vue'
import GridEditor from './GridEditor.vue'

const props = defineProps({
  modelValue: { type: Object, required: true },
  disabled: { type: Boolean, default: false },
  dataElPrefix: { type: String, default: 'regime-editor' },
})
const emit = defineEmits(['update:modelValue', 'remove', 'addGrid'])

const grids = computed(() => props.modelValue.grids || [])

function patch(field, value) {
  emit('update:modelValue', { ...props.modelValue, [field]: value })
}

function updateGrid(idx, grid) {
  const next = grids.value.slice()
  next[idx] = grid
  patch('grids', next)
}
function removeGrid(idx) {
  const next = grids.value.slice()
  next.splice(idx, 1)
  patch('grids', next)
}
</script>

<style scoped>
.regime-editor {
  background: var(--bg-elevated);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-base);
  padding: var(--space-3);
  margin-bottom: var(--space-3);
}
.re-header {
  margin-bottom: var(--space-3);
  padding-bottom: var(--space-3);
  border-bottom: 1px dashed var(--border-light);
}
.re-title-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
}
.re-name {
  flex: 1;
  max-width: 320px;
}
.re-priority {
  width: 110px;
}
.re-flags-row {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
}
.re-flags-label {
  font-size: 12px;
  color: var(--text-secondary);
  flex-shrink: 0;
  padding-top: var(--space-2);
  min-width: 80px;
}
.re-config-row {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-4);
  margin-top: var(--space-2);
}
.re-base-vol {
  margin-bottom: 0 !important;
}
.re-clear {
  margin-bottom: 0 !important;
}
.re-hint {
  margin-left: var(--space-2);
  color: var(--text-placeholder);
  font-size: 12px;
}
.re-grids-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--space-2);
}
.re-grids-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}
</style>