<template>
  <div class="profile-view fade-in-up" v-loading="loading">
    <!-- 顶部个人信息卡 -->
    <section class="hero-card">
      <div class="hero-bg"></div>
      <div class="hero-content">
        <div class="hero-avatar" :class="`role-${authStore.user?.role || 'viewer'}`">
          {{ avatarText }}
        </div>
        <div class="hero-info">
          <div class="hero-name">
            {{ authStore.user?.full_name || authStore.user?.username }}
            <span class="role-badge" :class="`role-${authStore.user?.role || 'viewer'}`">
              {{ ROLE_LABEL[authStore.user?.role] || '用户' }}
            </span>
          </div>
          <div class="hero-username text-mono">@{{ authStore.user?.username }}</div>
          <div class="hero-meta">
            <div class="meta-item">
              <el-icon><Message /></el-icon>
              <span>{{ authStore.user?.email || '未设置邮箱' }}</span>
            </div>
            <div class="meta-item">
              <el-icon><Clock /></el-icon>
              <span>上次登录: {{ formatDateTime(authStore.user?.last_login_at) }}</span>
            </div>
            <div class="meta-item">
              <el-icon><Calendar /></el-icon>
              <span>注册时间: {{ formatDateTime(authStore.user?.created_at) }}</span>
            </div>
          </div>
        </div>
        <div class="hero-actions">
          <el-button :icon="Lock" @click="pwdDialogVisible = true">
            修改密码
          </el-button>
        </div>
      </div>
    </section>

    <!-- 资料编辑 -->
    <div class="content-card">
      <div class="card-header">
        <div>
          <h3 class="card-title">个人资料</h3>
          <p class="card-sub">更新你的姓名和邮箱信息</p>
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
import {
  Lock, Check, Message, Clock, Calendar, View, TrendCharts, UserFilled
} from '@element-plus/icons-vue'
import { useAuthStore } from '../stores/auth'
import { formatDateTime } from '../utils/format'
import ChangePasswordDialog from '../components/ChangePasswordDialog.vue'

const authStore = useAuthStore()
const loading = ref(false)
const saving = ref(false)
const pwdDialogVisible = ref(false)

const ROLE_LABEL = { admin: '管理员', trader: '交易员', viewer: '只读用户' }

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
  max-width: 880px;
  margin: 0 auto;
  width: 100%;
}

.hero-card {
  position: relative;
  background: var(--bg-elevated);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-lg);
  padding: var(--space-6);
  overflow: hidden;
}

.hero-bg {
  position: absolute;
  inset: 0;
  background: var(--brand-gradient);
  opacity: 0.05;
  pointer-events: none;
}

.hero-bg::after {
  content: '';
  position: absolute;
  top: -120px;
  right: -120px;
  width: 320px;
  height: 320px;
  background: var(--brand-gradient);
  border-radius: 50%;
  opacity: 0.18;
  filter: blur(50px);
}

.hero-content {
  position: relative;
  display: flex;
  align-items: center;
  gap: var(--space-6);
  flex-wrap: wrap;
}

.hero-avatar {
  width: 96px;
  height: 96px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  color: white;
  font-size: 38px;
  font-weight: 700;
  flex-shrink: 0;
  box-shadow: var(--shadow-glow);
}

.hero-avatar.role-admin { background: var(--brand-gradient); }
.hero-avatar.role-trader { background: var(--color-up-gradient); }
.hero-avatar.role-viewer { background: linear-gradient(135deg, #5fa8ff, #82b9ff); }

.hero-info {
  flex: 1;
  min-width: 220px;
}

.hero-name {
  font-size: 22px;
  font-weight: 700;
  color: var(--text-primary);
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex-wrap: wrap;
}

.role-badge {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 10px;
  border-radius: var(--radius-xs);
  color: white;
}

.role-badge.role-admin { background: var(--brand-gradient); }
.role-badge.role-trader { background: var(--color-up-gradient); }
.role-badge.role-viewer { background: linear-gradient(135deg, #5fa8ff, #82b9ff); }

.hero-username {
  font-size: 13px;
  color: var(--text-secondary);
  margin-top: 4px;
}

.hero-meta {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin-top: var(--space-3);
}

.meta-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: 13px;
  color: var(--text-regular);
}

.meta-item .el-icon {
  color: var(--text-secondary);
  font-size: 14px;
}

.hero-actions {
  display: flex;
  gap: var(--space-2);
  align-items: flex-start;
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
  .hero-content { flex-direction: column; align-items: flex-start; }
}
</style>
