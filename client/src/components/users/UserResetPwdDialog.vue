<!--
  UserResetPwdDialog.vue — 重置密码弹窗

  Props:
    visible  (Boolean)
    loading  (Boolean)
    form     (Object)  — reactive pwdForm
    rules    (Object)
    target   (Object)  — {id, username, full_name, role}

  Emits:
    update:visible
    submit

  内部细节：
    - 自管 formRef
    - watch(visible) 开启时清校验
-->
<template>
  <el-dialog
    :model-value="visible"
    @update:model-value="(v) => $emit('update:visible', v)"
    title="重置密码"
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
      <el-form-item label="目标用户">
        <div class="target-user">
          <div class="avatar small" :class="`role-${target && target.role}`">
            {{ ((target && (target.full_name || target.username)) || '').charAt(0).toUpperCase() }}
          </div>
          <div>
            <div class="user-name">{{ target && target.username }}</div>
            <div class="text-secondary" style="font-size: 12px">
              {{ (target && target.full_name) || ROLE_LABEL[target && target.role] }}
            </div>
          </div>
        </div>
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
      <el-button @click="$emit('update:visible', false)">取消</el-button>
      <el-button type="primary" :loading="loading" @click="$emit('submit')">
        确认重置
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, watch } from 'vue'

const ROLE_LABEL = { admin: '管理员', trader: '交易员', viewer: '只读用户' }

const props = defineProps({
  visible: { type: Boolean, default: false },
  loading: { type: Boolean, default: false },
  form: { type: Object, required: true },
  rules: { type: Object, required: true },
  target: { type: Object, default: null },
})
defineEmits(['update:visible', 'submit'])

const formRef = ref(null)
defineExpose({ formRef, validate: () => formRef.value && formRef.value.validate() })

watch(() => props.visible, (v) => {
  if (v) setTimeout(() => formRef.value && formRef.value.clearValidate(), 50)
})
</script>

<style scoped>
.target-user {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-3);
  background: var(--bg-soft);
  border-radius: var(--radius-sm);
  border: 1px solid var(--border-base);
}
.avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  font-weight: 700;
  color: white;
  font-size: 14px;
  flex-shrink: 0;
}
.avatar.small { width: 30px; height: 30px; font-size: 12px; }
.avatar.role-admin { background: var(--brand-gradient); }
.avatar.role-trader { background: var(--color-up-gradient); }
.avatar.role-viewer { background: linear-gradient(135deg, #5fa8ff, #82b9ff); }
.user-name { font-weight: 600; color: var(--text-primary); font-size: 13px; }
.text-secondary { color: var(--text-secondary); }
</style>
