<!--
  GridEditor.vue — 单 grid 编辑器（task 11.7）

  Props：
    modelValue - 单 grid 对象（id / direction / step_offset / trigger_price /
                              volume / max_fires / fired_count / enabled / priority）
    disabled   - 整体禁用
  Emits：
    update:modelValue
    remove     - 删除按钮

  注：单个 grid 行编辑器（一行内嵌多个字段），非列表组件
-->
<template>
  <div class="grid-editor" :class="{ disabled }" :data-el="'grid-row-' + (modelValue.id || 'new')">
    <div class="grid-row">
      <el-form-item label="方向" label-width="48px" class="ge-field ge-dir">
        <el-radio-group
          :model-value="modelValue.direction"
          @update:model-value="patch('direction', $event)"
          :disabled="disabled"
          data-el="grid-dir"
        >
          <el-radio-button value="buy" data-el="grid-dir-buy">买</el-radio-button>
          <el-radio-button value="sell" data-el="grid-dir-sell">卖</el-radio-button>
        </el-radio-group>
      </el-form-item>

      <el-form-item label="触发价" label-width="56px" class="ge-field ge-price">
        <el-input-number
          :model-value="modelValue.trigger_price"
          @update:model-value="patch('trigger_price', $event)"
          :precision="3"
          :step="0.01"
          :min="0"
          :max="99999"
          :disabled="disabled"
          controls-position="right"
          data-el="grid-trigger-price"
        />
      </el-form-item>

      <el-form-item label="步长" label-width="48px" class="ge-field ge-step">
        <el-input-number
          :model-value="modelValue.step_offset"
          @update:model-value="patch('step_offset', $event)"
          :precision="3"
          :step="0.01"
          :disabled="disabled"
          controls-position="right"
          data-el="grid-step-offset"
        />
      </el-form-item>

      <el-form-item label="量" label-width="36px" class="ge-field ge-vol">
        <el-input-number
          :model-value="modelValue.volume"
          @update:model-value="patch('volume', $event)"
          :step="100"
          :min="0"
          :max="999999"
          :disabled="disabled"
          controls-position="right"
          data-el="grid-volume"
        />
      </el-form-item>

      <el-form-item label="最多触发" label-width="60px" class="ge-field ge-max">
        <el-input-number
          :model-value="modelValue.max_fires ?? null"
          @update:model-value="patch('max_fires', $event)"
          :min="0"
          :max="9999"
          :disabled="disabled"
          controls-position="right"
          placeholder="∞"
          data-el="grid-max-fires"
        />
      </el-form-item>

      <el-form-item label="已触发" label-width="60px" class="ge-field ge-fired">
        <span class="ge-fired-count">{{ modelValue.fired_count || 0 }}</span>
      </el-form-item>

      <el-form-item label="启用" label-width="40px" class="ge-field ge-enabled">
        <el-switch
          :model-value="modelValue.enabled !== false"
          @update:model-value="patch('enabled', $event)"
          :disabled="disabled"
          data-el="grid-enabled"
        />
      </el-form-item>

      <el-form-item label="优先级" label-width="60px" class="ge-field ge-priority">
        <el-input-number
          :model-value="modelValue.priority"
          @update:model-value="patch('priority', $event)"
          :min="0"
          :max="9999"
          :disabled="disabled"
          controls-position="right"
          data-el="grid-priority"
        />
      </el-form-item>

      <div class="ge-actions">
        <el-button
          link
          type="danger"
          :disabled="disabled"
          @click="emit('remove')"
          data-el="grid-remove"
        >
          <el-icon><Delete /></el-icon>
        </el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { Delete } from '@element-plus/icons-vue'

const props = defineProps({
  modelValue: { type: Object, required: true },
  disabled: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue', 'remove'])

function patch(field, value) {
  emit('update:modelValue', { ...props.modelValue, [field]: value })
}
</script>

<style scoped>
.grid-editor {
  background: var(--bg-base);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-sm);
  padding: var(--space-2) var(--space-3);
  margin-bottom: var(--space-2);
}
.grid-editor.disabled {
  opacity: 0.7;
}
.grid-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
}
.ge-field {
  margin-bottom: 0 !important;
}
.ge-fired-count {
  font-family: var(--font-mono);
  color: var(--text-secondary);
  padding: 0 var(--space-2);
}
.ge-actions {
  margin-left: auto;
}
</style>