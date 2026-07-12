<!--
  T0TaskCreateDialog.vue — 新建 T0Task 弹窗（v18 change t0-task-management, v26 universalize-stockcode-autocomplete）

  Props:
    visible   (Boolean) — 双向绑定显示状态
    loading   (Boolean) — 提交 loading（外层 store 操作）
    defaultStockCode (String) — 默认股票代码 (v26 新增, 从父组件当前 stockCode 带入)

  Emits:
    update:visible — 关闭弹窗
    submit(form)   — 用户点击创建（外层调 store.createTask）

  字段：
    - stock_code      必填, v26 起走 StockCodeAutocomplete (cache 全市场 5529)
    - base_volume     底仓（默认 0，可空 — 让仓位变化完全在 target_volume 层）
    - target_volume   目标开仓量（必填；可负表示净减仓）
    - coefficient     配平系数（默认 1.0，沿用 v13 REQ-TRADE-005 语义）
    - note            备注（可选）

  注意：
    - v26 删除 stockOptions prop（v18 旧设计，从 holdings 取持仓股优先显示），改用全市场 cache
    - 校验：stock_code 必选、target_volume 必填且为整数
-->
<template>
  <el-dialog
    :model-value="visible"
    @update:model-value="(v) => $emit('update:visible', v)"
    title="新建 T0 任务"
    width="520px"
    :close-on-click-modal="false"
    align-center
    @open="onOpen"
  >
    <el-form
      ref="formRef"
      :model="form"
      :rules="rules"
      label-position="top"
      size="default"
    >
      <el-form-item label="股票代码" prop="stock_code">
        <!-- v26: StockCodeAutocomplete 通用组件 (cache 全市场 5529 跨页面共享) -->
        <StockCodeAutocomplete
          v-model="form.stock_code"
          placeholder="输入代码 / 名称 / 首字母"
          clearable
        />
      </el-form-item>

      <el-form-item label="底仓量（保留部分底仓）" prop="base_volume">
        <el-input-number
          v-model="form.base_volume"
          :min="0"
          :step="100"
          :value-on-clear="0"
          style="width: 100%"
        />
        <span class="field-hint">配平时仓位会保留底仓；=0 时一键平仓回空仓</span>
      </el-form-item>

      <el-form-item label="目标开仓量" prop="target_volume">
        <el-input-number
          v-model="form.target_volume"
          :step="100"
          style="width: 100%"
        />
        <span class="field-hint">相对底仓的净增量；可负表示净减仓</span>
      </el-form-item>

      <el-form-item label="配平系数" prop="coefficient">
        <el-input-number
          v-model="form.coefficient"
          :min="0"
          :max="2"
          :step="0.1"
          :precision="2"
          style="width: 100%"
        />
      </el-form-item>

      <el-form-item label="备注" prop="note">
        <el-input
          v-model="form.note"
          placeholder="可选，便于搜索/识别"
          maxlength="255"
          show-word-limit
        />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="$emit('update:visible', false)">取消</el-button>
      <el-button type="primary" :loading="loading" @click="onSubmit">
        创建
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, reactive, watch } from 'vue'
import StockCodeAutocomplete from '../StockCodeAutocomplete.vue'

const props = defineProps({
  visible: { type: Boolean, default: false },
  loading: { type: Boolean, default: false },
  // v26 新增: 从父组件带入默认股票代码 (替代 v18 的 stockOptions 持仓股优先)
  defaultStockCode: { type: String, default: '' }
})
const emit = defineEmits(['update:visible', 'submit'])

const formRef = ref(null)

// 表单初始值
const initialForm = () => ({
  stock_code: props.defaultStockCode || '',
  base_volume: 0,
  target_volume: 0,
  coefficient: 1.0,
  note: '',
})
const form = reactive(initialForm())

// 校验规则
const rules = {
  stock_code: [{ required: true, message: '请选择股票', trigger: 'change' }],
  target_volume: [
    {
      validator: (_r, _v, cb) => {
        if (form.target_volume === '' || form.target_volume === null || Number.isNaN(Number(form.target_volume))) {
          return cb(new Error('请输入目标开仓量'))
        }
        cb()
      },
      trigger: 'change',
    },
  ],
}

function onOpen() {
  // 每次打开重置
  Object.assign(form, initialForm())
  setTimeout(() => formRef.value && formRef.value.clearValidate(), 50)
}

watch(() => props.visible, (v) => { if (v) onOpen() })

function onSubmit() {
  formRef.value.validate((valid) => {
    if (!valid) return
    // v27 重构后 StockCodeAutocomplete modelValue 永远是纯 stock_code (600519.SH),
    //   无需 split, 直接 spread form 给外层
    emit('submit', { ...form })
  })
}

defineExpose({ formRef, validate: () => formRef.value && formRef.value.validate() })
</script>

<style scoped>
.field-hint {
  font-size: 11px;
  color: var(--el-text-color-secondary, #909399);
  margin-left: 8px;
  line-height: 1.2;
}
</style>
