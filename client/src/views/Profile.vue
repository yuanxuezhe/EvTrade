<template>
  <div class="profile-view fade-in-up" v-loading="loading">
    <!-- 资料编辑 (B 组统一: 直接 .content-card + .card-header, 不再有独立 hero-card) -->
    <div class="content-card">
      <div class="card-header">
        <div>
          <h3 class="card-title">个人资料</h3>
          <p class="card-sub">更新你的姓名和邮箱信息</p>
        </div>
        <!-- 原 hero-card 用户信息合并到 card-header 右侧 + 修改密码按钮 -->
        <div class="card-header-extra">
          <span class="profile-avatar" :class="`role-${authStore.user?.role || 'viewer'}`">
            {{ avatarText }}
          </span>
          <div class="profile-meta">
            <span class="profile-name">
              {{ authStore.user?.full_name || authStore.user?.username }}
              <el-tag size="small" :type="ROLE_TAG_TYPE[authStore.user?.role] || 'info'" effect="light">
                {{ ROLE_LABEL[authStore.user?.role] || '用户' }}
              </el-tag>
            </span>
            <span class="profile-line">{{ authStore.user?.email || '未设置邮箱' }}</span>
          </div>
          <el-button :icon="Lock" @click="pwdDialogVisible = true">修改密码</el-button>
        </div>
      </div>
      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-position="top"
        size="default"
        class="profile-form"
      >
        <el-form-item label="用户名">
          <el-input :model-value="authStore.user?.username" disabled />
        </el-form-item>
        <el-form-item label="角色">
          <el-input :model-value="ROLE_LABEL[authStore.user?.role] || '用户'" disabled />
        </el-form-item>
        <el-form-item label="姓名" prop="full_name">
          <el-input v-model="form.full_name" placeholder="请输入姓名" clearable />
        </el-form-item>
        <el-form-item label="邮箱" prop="email">
          <el-input v-model="form.email" placeholder="请输入邮箱" clearable />
        </el-form-item>
        <el-form-item>
          <el-button
            type="primary"
            :icon="Check"
            :loading="saving"
            @click="handleSave"
          >
            保存修改
          </el-button>
          <el-button @click="resetForm" :disabled="saving">重置</el-button>
        </el-form-item>
      </el-form>
    </div>

    <!-- 权限说明 -->
    <div class="content-card">
      <div class="card-header">
        <div>
          <h3 class="card-title">权限说明</h3>
          <p class="card-sub">当前账号可执行的操作</p>
        </div>
      </div>
      <div class="perm-grid">
        <div class="perm-item" :class="{ granted: canView }">
          <el-icon class="perm-icon"><View /></el-icon>
          <div class="perm-content">
            <div class="perm-name">查看数据</div>
            <div class="perm-desc">查看持仓、委托、成交、资金信息</div>
          </div>
          <el-tag :type="canView ? 'success' : 'info'" size="small">
            {{ canView ? '已开通' : '未开通' }}
          </el-tag>
        </div>
        <div class="perm-item" :class="{ granted: canTrade }">
          <el-icon class="perm-icon"><TrendCharts /></el-icon>
          <div class="perm-content">
            <div class="perm-name">交易下单</div>
            <div class="perm-desc">创建委托、撤单、操作持仓</div>
          </div>
          <el-tag :type="canTrade ? 'success' : 'info'" size="small">
            {{ canTrade ? '已开通' : '未开通' }}
          </el-tag>
        </div>
        <div class="perm-item" :class="{ granted: canManage }">
          <el-icon class="perm-icon"><UserFilled /></el-icon>
          <div class="perm-content">
            <div class="perm-name">用户管理</div>
            <div class="perm-desc">创建、编辑、删除系统用户</div>
          </div>
          <el-tag :type="canManage ? 'success' : 'info'" size="small">
            {{ canManage ? '已开通' : '未开通' }}
          </el-tag>
        </div>
      </div>
    </div>

    <ChangePasswordDialog v-model="pwdDialogVisible" />
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Lock, Check, View, TrendCharts, UserFilled } from '@element-plus/icons-vue'
import { useAuthStore } from '../stores/auth'
import ChangePasswordDialog from '../components/ChangePasswordDialog.vue'

const authStore = useAuthStore()
const loading = ref(false)
const saving = ref(false)
const pwdDialogVisible = ref(false)

const ROLE_LABEL = { admin: '管理员', trader: '交易员', viewer: '只读用户' }
// el-tag type 映射 (admin=red, trader=warning, viewer=info)
const ROLE_TAG_TYPE = { admin: 'danger', trader: 'warning', viewer: 'info' }

const avatarText = computed(() => {
  const n = authStore.user?.full_name || authStore.user?.username
  return n ? n.charAt(0).toUpperCase() : '?'
})

const canView = computed(() => !!authStore.isAuthenticated)
const canTrade = computed(() => authStore.isTrader)
const canManage = computed(() => authStore.isAdmin)

const formRef = ref(null)
const form = reactive({
  full_name: '',
  email: ''
})

const rules = {
  full_name: [{ max: 32, message: '姓名最多 32 个字符', trigger: 'blur' }],
  email: [
    {
      validator: (_r, v, cb) =>
        !v || /^[\w.+-]+@[\w-]+\.[\w.-]+$/.test(v) ? cb() : cb(new Error('邮箱格式不正确')),
      trigger: 'blur'
    }
  ]
}

function fillForm() {
  form.full_name = authStore.user?.full_name || ''
  form.email = authStore.user?.email || ''
}

watch(() => authStore.user, fillForm, { immediate: true })

function resetForm() {
  fillForm()
  formRef.value?.clearValidate()
}

async function handleSave() {
  if (!formRef.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  saving.value = true
  try {
    await authStore.updateProfile({
      full_name: form.full_name.trim(),
      email: form.email.trim()
    })
    ElMessage.success('资料已更新')
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '更新失败')
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  loading.value = true
  try {
    await authStore.fetchMe()
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.profile-view {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
  flex: 1 1 0;
  min-height: 0;
  overflow: auto;
  max-width: 880px;
  margin: 0 auto;
  width: 100%;
}

/* card-header 右侧合并: 原 hero 信息 + 修改密码按钮 */
.card-header-extra {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  flex-wrap: wrap;
}

.profile-avatar {
  width: 44px;
  height: 44px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  color: white;
  font-size: 18px;
  font-weight: 700;
  flex-shrink: 0;
  box-shadow: var(--shadow-glow);
}
.profile-avatar.role-admin { background: var(--brand-gradient); }
.profile-avatar.role-trader { background: var(--color-up-gradient); }
.profile-avatar.role-viewer { background: linear-gradient(135deg, #5fa8ff, #82b9ff); }

.profile-meta {
  display: flex;
  flex-direction: column;
  gap: 2px;
  line-height: 1.4;
}
.profile-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.profile-line {
  font-size: 12px;
  color: var(--text-secondary);
}

.content-card {
  background: var(--bg-elevated);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-lg);
  padding: var(--space-5);
}

.card-header {
  margin-bottom: var(--space-4);
  padding-bottom: var(--space-3);
  border-bottom: 1px solid var(--border-light);
}

.card-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}

.card-sub {
  font-size: 12px;
  color: var(--text-secondary);
  margin-top: 2px;
}

.profile-form {
  max-width: 480px;
}

.perm-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--space-4);
}

.perm-item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-4);
  background: var(--bg-soft);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-md);
  opacity: 0.55;
  transition: all var(--transition-fast);
}

.perm-item.granted {
  opacity: 1;
  background: var(--bg-elevated);
  border-color: var(--brand-primary);
  box-shadow: 0 0 0 3px var(--brand-gradient-soft);
}

.perm-icon {
  width: 40px;
  height: 40px;
  border-radius: var(--radius-sm);
  display: grid;
  place-items: center;
  background: var(--bg-soft);
  color: var(--text-secondary);
  font-size: 18px;
  flex-shrink: 0;
}

.perm-item.granted .perm-icon {
  background: var(--brand-gradient-soft);
  color: var(--brand-primary);
}

.perm-content {
  flex: 1;
  min-width: 0;
}

.perm-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.perm-desc {
  font-size: 12px;
  color: var(--text-secondary);
  margin-top: 2px;
}

@media (max-width: 720px) {
  .perm-grid { grid-template-columns: 1fr; }
  .card-header-extra { width: 100%; flex-direction: row; }
}
</style>
