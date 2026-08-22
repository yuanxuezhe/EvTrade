<!--
  T0TaskCreateDialog.vue — 新建 T0Task 弹窗 (change t0-task-management / universalize-stockcode-autocomplete / external-stockcode + inline)

  Props:
    visible   (Boolean) — 双向绑定显示状态 (inline=true 时忽略)
    loading   (Boolean) — 提交 loading (外层 store 操作)
    inline    (Boolean) — 不渲染外层 el-dialog，直接展示表单 (供其他组件嵌入 dialog body)
    defaultStockCode (String) — 默认股票代码 (从父组件当前 stockCode 带入)
    externalStockCode (String) — 父组件外部传入的 stock_code (HoldingsPanel 选中后),
                                  优先级高于 defaultStockCode. 变更时自动写 form.stock_code.

  Emits:
    submit(form)   — 用户点击创建 (外层调 store.createTask)

  注意：
    - 无 stockOptions prop (不从 holdings 取持仓股优先显示), 改用全市场 cache
    - 校验：stock_code 必选、target_volume 必填且为整数
    - 优先级 defaultStockCode > externalStockCode (dialog 打开时); dialog 打开后 externalStockCode
      变化 → 立即写入 form (让 HoldingsPanel 单击能驱动表单)
    - inline=true 时: 跳过 el-dialog 包裹, 不处理 visible (父组件控制 dialog lifecycle),
      表单 onSubmit 直接 emit submit, 不 emit update:visible; footer 按钮 "创建/取消" 仍展示
-->
<template>
  <el-form
    v-if="inline"
    ref="formRef"
    :model="form"
    :rules="rules"
    label-position="top"
    size="default"
    class="t0-task-create-form"
  >
    <el-form-item label="股票代码" prop="stock_code">
      <StockCodePicker
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
    <div class="inline-footer">
      <el-button @click="onInlineCancel">取消</el-button>
      <el-button type="primary" :loading="loading" @click="onSubmit">创建</el-button>
    </div>
  </el-form>

  <el-dialog
    v-else
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
        <StockCodePicker
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
      <el-button type="primary" :loading="loading" @click="onSubmit">创建</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, reactive, watch } from 'vue'
import StockCodePicker from '../StockCodePicker.vue'

const props = defineProps({
  visible: { type: Boolean, default: false },
  loading: { type: Boolean, default: false },
  // true 时不渲染外层 el-dialog, 直接展示表单 (供其他组件嵌入 dialog body)
  inline: { type: Boolean, default: false },
  // 从父组件带入默认股票代码 (不用 stockOptions 持仓股优先)
  defaultStockCode: { type: String, default: '' },
  // 父组件外部传入 (HoldingsPanel @select-stock). 优先级高于 defaultStockCode.
  //           dialog 打开时使用, dialog 打开后变化也立即同步到 form (单击驱动).
  externalStockCode: { type: String, default: '' }
})
const emit = defineEmits(['update:visible', 'submit', 'cancel'])

// 表单初始值 (externalStockCode 优先)
const initialForm = () => ({
  stock_code: props.externalStockCode || props.defaultStockCode || '',
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

const formRef = ref(null)

function onOpen() {
  // 每次打开重置
  Object.assign(form, initialForm())
  setTimeout(() => formRef.value && formRef.value.clearValidate(), 50)
}

watch(() => props.visible, (v) => { if (v && !props.inline) onOpen() })

// 监听 externalStockCode 实时驱动 form (HoldingsPanel 单击后立即回填)
watch(() => props.externalStockCode, (v) => {
  if (v && v !== form.stock_code) {
    form.stock_code = v
    setTimeout(() => formRef.value && formRef.value.clearValidate(['stock_code']), 50)
  }
})

// inline 模式: externalStockCode 变化 → 初始化 form (因 inline 不走 onOpen)
watch(() => props.externalStockCode, (v) => {
  if (props.inline && !form.stock_code && v) {
    form.stock_code = v
  }
}, { immediate: true })

function onSubmit() {
  formRef.value.validate((valid) => {
    if (!valid) return
    emit('submit', { ...form })
  })
}

function onInlineCancel() {
  emit('cancel')
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
.inline-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 12px;
}
</style>