<template>
  <el-dialog
    v-model="visible"
    title="修改密码"
    width="420px"
    :close-on-click-modal="false"
    align-center
  >
    <el-form
      ref="formRef"
      :model="form"
      :rules="rules"
      label-position="top"
      size="default"
    >
      <el-form-item label="原密码" prop="old_password">
        <el-input
          v-model="form.old_password"
          type="password"
          show-password
          placeholder="请输入当前密码"
        />
      </el-form-item>
      <el-form-item label="新密码" prop="new_password">
        <el-input
          v-model="form.new_password"
          type="password"
          show-password
          placeholder="至少 6 位"
        />
      </el-form-item>
      <el-form-item label="确认新密码" prop="confirm">
        <el-input
          v-model="form.confirm"
          type="password"
          show-password
          placeholder="再次输入新密码"
        />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="loading" @click="handleSubmit">
        确认修改
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '../stores/auth'

const props = defineProps({
  modelValue: { type: Boolean, default: false }
})
const emit = defineEmits(['update:modelValue', 'success'])

const visible = ref(props.modelValue)
const loading = ref(false)
const formRef = ref(null)
const authStore = useAuthStore()

const form = reactive({
  old_password: '',
  new_password: '',
  confirm: ''
})

const rules = {
  old_password: [{ required: true, message: '请输入原密码', trigger: 'blur' }],
  new_password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 6, message: '密码长度至少 6 位', trigger: 'blur' }
  ],
  confirm: [
    { required: true, message: '请再次输入新密码', trigger: 'blur' },
    {
      validator: (_r, v, cb) =>
        v === form.new_password ? cb() : cb(new Error('两次输入的新密码不一致')),
      trigger: 'blur'
    }
  ]
}

watch(visible, (v) => emit('update:modelValue', v))
watch(
  () => props.modelValue,
  (v) => {
    visible.value = v
    if (v) reset()
  }
)

function reset() {
  form.old_password = ''
  form.new_password = ''
  form.confirm = ''
  formRef.value?.clearValidate()
}

async function handleSubmit() {
  if (!formRef.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  loading.value = true
  try {
    await authStore.changePassword(form.old_password, form.new_password)
    ElMessage.success('密码已修改，请重新登录')
    visible.value = false
    emit('success')
    // 自动登出
    setTimeout(async () => {
      await authStore.logout()
      window.location.href = '/login'
    }, 800)
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '修改失败')
  } finally {
    loading.value = false
  }
}
</script>
