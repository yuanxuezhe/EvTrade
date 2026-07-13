<!--
  StrategyConfig.vue — 策略基本信息表单（task 11.4）

  字段：stock_code / type [general | t0] / reference_price / base_volume / note
  Props：
    modelValue - 表单数据对象（v-model）
    disabled   - 整体禁用（detail 视图用）
  Emits：
    update:modelValue - v-model 同步
-->
<template>
  <div class="strat-config">
    <el-form
      :model="form"
      :rules="rules"
      label-width="100px"
      label-position="right"
      class="strat-config-form"
      :disabled="disabled"
    >
      <el-form-item label="股票代码" prop="stock_code">
        <!-- v29: 切到 StockCodePicker (代码 + 名称左右拼接, blur 时未选自动清空) -->
        <StockCodePicker
          v-model="form.stock_code"
          placeholder="输入代码 / 名称 / 首字母"
          clearable
          :disabled="disabled"
          data-el="stock-code-input"
        />
      </el-form-item>

      <el-form-item label="策略类型" prop="type">
        <el-radio-group v-model="form.type" data-el="type-radio-group">
          <el-radio-button
            v-for="opt in TYPE_OPTIONS"
            :key="opt.value"
            :value="opt.value"
            :data-el="'type-radio-' + opt.value"
          >
            {{ opt.label }}
          </el-radio-button>
        </el-radio-group>
        <span class="form-hint">{{ TYPE_HINT[form.type] }}</span>
      </el-form-item>

      <el-form-item label="参考价" prop="reference_price">
        <el-input-number
          v-model="form.reference_price"
          :precision="3"
          :step="0.01"
          :min="0"
          :max="99999"
          controls-position="right"
          data-el="ref-price-input"
        />
      </el-form-item>

      <el-form-item label="基础量" prop="base_volume">
        <el-input-number
          v-model="form.base_volume"
          :step="100"
          :min="0"
          :max="999999"
          controls-position="right"
          data-el="base-vol-input"
        />
        <span class="form-hint">单位：股（整百）。底仓/单网格量参考</span>
      </el-form-item>

      <el-form-item label="备注" prop="note">
        <el-input
          v-model="form.note"
          type="textarea"
          :rows="2"
          maxlength="200"
          show-word-limit
          placeholder="（可选）说明该策略用途 / 风控要点"
          data-el="note-textarea"
        />
      </el-form-item>
    </el-form>
  </div>
</template>

<script setup>
import { computed, watch } from 'vue'
import { TYPE_LABEL } from './composables/useStrategy'
import StockCodePicker from '../../components/StockCodePicker.vue'

const props = defineProps({
  modelValue: { type: Object, required: true },
  disabled: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue'])

const TYPE_OPTIONS = [
  { value: 'general', label: TYPE_LABEL.general },
  { value: 't0', label: TYPE_LABEL.t0 },
]
const TYPE_HINT = {
  general: '通用策略（多 regime + 多 grid，灵活配置）',
  t0: 'T0 策略（关联 Order.user_def=str(id)，T0 端点 JOIN 过滤）',
}

const form = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

// 初次加载若 type 缺失 → 默认 general
watch(
  () => form.value.type,
  (v) => {
    if (v && !['general', 't0'].includes(v)) form.value.type = 'general'
  },
  { immediate: true }
)

// v29 重构后 StockCodePicker modelValue 永远是纯 stock_code (600519.SH),
//   删掉之前的 watch split 逻辑, 控件内部已自行保证

const rules = {
  stock_code: [
    { required: true, message: '请输入股票代码', trigger: 'blur' },
    {
      validator: (_r, v, cb) =>
        /^[0-9]{6}\.(SH|SZ)$/.test(v) ? cb() : cb(new Error('格式：6位数字.SH/SZ')),
      trigger: 'blur',
    },
  ],
  type: [{ required: true, message: '请选择类型', trigger: 'change' }],
  reference_price: [
    { required: true, message: '请输入参考价', trigger: 'blur' },
    {
      validator: (_r, v, cb) =>
        v > 0 ? cb() : cb(new Error('参考价必须 > 0')),
      trigger: 'blur',
    },
  ],
  base_volume: [
    { required: true, message: '请输入基础量', trigger: 'blur' },
    {
      validator: (_r, v, cb) =>
        v >= 0 ? cb() : cb(new Error('基础量不能为负')),
      trigger: 'blur',
    },
  ],
}
</script>

<style scoped>
.strat-config {
  padding: var(--space-4);
}
.strat-config-form {
  max-width: 540px;
}
.form-hint {
  margin-left: var(--space-3);
  color: var(--text-placeholder);
  font-size: 12px;
}
</style>