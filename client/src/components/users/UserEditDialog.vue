<!--
  UserEditDialog.vue — 新建 / 编辑用户弹窗

  Props:
    visible   (Boolean) — 双向绑定显示状态
    loading   (Boolean) — 提交 loading
    form      (Object)  — reactive 表单
    rules     (Object)  — 校验规则

  Emits:
    update:visible — 关闭弹窗
    submit         — 用户点击创建/保存（外层调 composable.submitEdit）

  内部细节：
    - 自管 formRef（el-form 校验、清错误用）
    - watch(visible) 开启时清校验（避免旧错误残留）
-->
<template>
  <el-dialog
    :model-value="visible"
    @update:model-value="(v) => $emit('update:visible', v)"
    :title="form.id ? '编辑用户' : '新建用户'"
    width="480px"
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
      <el-form-item label="用户名" prop="username">
        <el-input
          v-model="form.username"
          placeholder="3-32位字母/数字/_/-/."
          :disabled="!!form.id"
        />
      </el-form-item>

      <el-form-item
        v-if="!form.id"
        label="初始密码"
        prop="password"
      >
        <el-input
          v-model="form.password"
          type="password"
          show-password
          placeholder="至少 6 位"
        />
      </el-form-item>

      <el-form-item label="角色" prop="role">
        <el-radio-group v-model="form.role">
          <el-radio-button value="admin">管理员</el-radio-button>
          <el-radio-button value="trader">交易员</el-radio-button>
          <el-radio-button value="viewer">只读用户</el-radio-button>
        </el-radio-group>
      </el-form-item>

      <el-form-item label="姓名" prop="full_name">
        <el-input v-model="form.full_name" placeholder="可选" />
      </el-form-item>

      <el-form-item label="邮箱" prop="email">
        <el-input v-model="form.email" placeholder="可选" />
      </el-form-item>

      <el-form-item v-if="!form.id" label="启用状态" prop="is_active">
        <el-switch
          v-model="form.is_active"
          active-text="启用"
          inactive-text="禁用"
          inline-prompt
        />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="$emit('update:visible', false)">取消</el-button>
      <el-button type="primary" :loading="loading" @click="$emit('submit')">
        {{ form.id ? '保存' : '创建' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, watch } from 'vue'

const props = defineProps({
  visible: { type: Boolean, default: false },
  loading: { type: Boolean, default: false },
  form: { type: Object, required: true },
  rules: { type: Object, required: true },
})
defineEmits(['update:visible', 'submit'])

const formRef = ref(null)
defineExpose({ formRef, validate: () => formRef.value && formRef.value.validate() })

watch(() => props.visible, (v) => {
  if (v) setTimeout(() => formRef.value && formRef.value.clearValidate(), 50)
})
</script>

<style scoped>
</style>
