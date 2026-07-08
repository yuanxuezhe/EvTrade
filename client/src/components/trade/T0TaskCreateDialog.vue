<!--
  T0TaskCreateDialog.vue — 新建 T0Task 弹窗（v18 change t0-task-management）

  Props:
    visible   (Boolean) — 双向绑定显示状态
    loading   (Boolean) — 提交 loading（外层 store 操作）
    stockOptions (Array<{code, name}>) — 可选股票列表（从 holdings 取）

  Emits:
    update:visible — 关闭弹窗
    submit(form)   — 用户点击创建（外层调 store.createTask）

  字段：
    - stock_code      必填，从下拉选
    - base_volume     底仓（默认 0，可空 — 让仓位变化完全在 target_volume 层）
    - target_volume   目标开仓量（必填；可负表示净减仓）
    - coefficient     配平系数（默认 1.0，沿用 v13 REQ-TRADE-005 语义）
    - note            备注（可选）

  注意：
    - stockOptions 中按 code + name 展示（持仓股优先）
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
        <el-select
          v-model="form.stock_code"
          placeholder="选择股票"
          filterable
          style="width: 100%"
        >
          <el-option
            v-for="o in stockOptions"
            :key="o.code"
            :value="o.code"
            :label="`${o.code} ${o.name || ''}`"
          />
        </el-select>
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

const props = defineProps({
  visible: { type: Boolean, default: false },
  loading: { type: Boolean, default: false },
  stockOptions: { type: Array, default: () => [] },
})
const emit = defineEmits(['update:visible', 'submit'])

const formRef = ref(null)

// 表单初始值
const initialForm = () => ({
  stock_code: '',
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
    // 提交外层 event（form 已经是 reactive 对象，外层拿 reactive 引用即可）
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
