<template>
  <div class="login-page">
    <!-- 背景装饰 -->
    <div class="bg-decor">
      <div class="blob blob-1"></div>
      <div class="blob blob-2"></div>
      <div class="blob blob-3"></div>
      <div class="grid-overlay"></div>
    </div>

    <!-- 左侧品牌信息 -->
    <aside class="brand-pane">
      <div class="brand-top">
        <div class="brand-logo">
          <el-icon :size="28"><TrendCharts /></el-icon>
        </div>
        <div>
          <div class="brand-name">EvTrade</div>
          <div class="brand-slogan">智能交易终端</div>
        </div>
      </div>

      <div class="brand-hero">
        <h1 class="hero-title">
          <span class="gradient-text">现代化</span>的<br />
          交易决策中心
        </h1>
        <p class="hero-desc">
          覆盖委托、查询、持仓、资产管理。<br />
          专业、高效、安全的交易工作台。
        </p>
        <div class="feature-list">
          <div class="feature-item">
            <el-icon class="fi-icon"><Check /></el-icon>
            <span>JWT 安全鉴权 + 角色权限</span>
          </div>
          <div class="feature-item">
            <el-icon class="fi-icon"><Check /></el-icon>
            <span>实时行情与委托追踪</span>
          </div>
          <div class="feature-item">
            <el-icon class="fi-icon"><Check /></el-icon>
            <span>多终端响应式适配</span>
          </div>
        </div>
      </div>

      <div class="brand-footer">
        © {{ year }} EvTrade · 智能交易终端
      </div>
    </aside>

    <!-- 右侧登录表单 -->
    <main class="login-pane">
      <div class="login-card">
        <h2 class="login-title">欢迎回来</h2>
        <p class="login-sub">使用账号密码登录您的交易终端</p>

        <el-form
          ref="formRef"
          :model="form"
          :rules="rules"
          size="large"
          label-position="top"
          @submit.prevent="handleLogin"
        >
          <el-form-item label="用户名" prop="username">
            <el-input
              v-model="form.username"
              placeholder="请输入用户名"
              :prefix-icon="User"
              clearable
              autofocus
              @keyup.enter="handleLogin"
            />
          </el-form-item>

          <el-form-item label="密码" prop="password">
            <el-input
              v-model="form.password"
              type="password"
              placeholder="请输入密码"
              :prefix-icon="Lock"
              show-password
              clearable
              @keyup.enter="handleLogin"
            />
          </el-form-item>

          <div class="form-row">
            <el-checkbox v-model="remember">记住用户名</el-checkbox>
          </div>

          <el-button
            type="primary"
            size="large"
            class="login-btn"
            :loading="loading"
            @click="handleLogin"
          >
            登 录
          </el-button>
        </el-form>

        <div class="theme-toggle">
          <el-button text @click="uiStore.toggleTheme">
            <el-icon><Sunny v-if="uiStore.theme === 'dark'" /><Moon v-else /></el-icon>
            <span style="margin-left: 4px">{{ uiStore.theme === 'dark' ? '浅色' : '深色' }}模式</span>
          </el-button>
        </div>
      </div>
    </main>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  User, Lock, TrendCharts, Check, Sunny, Moon
} from '@element-plus/icons-vue'
import { useAuthStore } from '../stores/auth'
import { useUiStore } from '../stores/ui'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const uiStore = useUiStore()

const REMEMBER_KEY = 'evtrade-remember-username'

const formRef = ref(null)
const loading = ref(false)
const remember = ref(true)
const year = new Date().getFullYear()

const form = reactive({
  username: '',
  password: ''
})

const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '密码长度至少 6 位', trigger: 'blur' }
  ]
}

onMounted(() => {
  const saved = localStorage.getItem(REMEMBER_KEY)
  if (saved) form.username = saved
})

async function handleLogin() {
  if (!formRef.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  loading.value = true
  try {
    const user = await authStore.login(form.username.trim(), form.password)
    if (remember.value) {
      localStorage.setItem(REMEMBER_KEY, form.username.trim())
    } else {
      localStorage.removeItem(REMEMBER_KEY)
    }
    ElMessage.success(`欢迎回来，${user.full_name || user.username}`)
    if (user.must_change_password) {
      ElMessage.warning('这是首次登录，请修改默认密码')
      router.replace('/profile')
    } else {
      const redirect = route.query.redirect || '/'
      router.replace(redirect)
    }
  } catch (e) {
    const msg = e.response?.data?.detail || '登录失败'
    ElMessage.error(msg)
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  position: relative;
  width: 100vw;
  height: 100vh;
  display: grid;
  grid-template-columns: 1fr 1fr;
  overflow: hidden;
  background: var(--bg-base);
}

/* 背景 */
.bg-decor {
  position: absolute;
  inset: 0;
  overflow: hidden;
  pointer-events: none;
  z-index: 0;
}

.blob {
  position: absolute;
  border-radius: 50%;
  filter: blur(80px);
  opacity: 0.4;
}

.blob-1 {
  width: 480px;
  height: 480px;
  background: var(--brand-gradient);
  top: -120px;
  left: -120px;
  animation: float 12s ease-in-out infinite;
}

.blob-2 {
  width: 360px;
  height: 360px;
  background: linear-gradient(135deg, #7c5cff 0%, #4f7cff 100%);
  bottom: -100px;
  right: 30%;
  animation: float 16s ease-in-out infinite reverse;
}

.blob-3 {
  width: 280px;
  height: 280px;
  background: linear-gradient(135deg, #16b572 0%, #5fa8ff 100%);
  top: 30%;
  right: -80px;
  animation: float 14s ease-in-out infinite;
}

.grid-overlay {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(79, 124, 255, 0.06) 1px, transparent 1px),
    linear-gradient(90deg, rgba(79, 124, 255, 0.06) 1px, transparent 1px);
  background-size: 40px 40px;
  mask-image: radial-gradient(ellipse at center, black 50%, transparent 100%);
}

@keyframes float {
  0%, 100% { transform: translate(0, 0); }
  50% { transform: translate(40px, -30px); }
}

/* 左侧品牌区 */
.brand-pane {
  position: relative;
  z-index: 1;
  padding: var(--space-8) var(--space-10);
  display: flex;
  flex-direction: column;
  justify-content: space-between;
}

.brand-top {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.brand-logo {
  width: 48px;
  height: 48px;
  border-radius: var(--radius-md);
  background: var(--brand-gradient);
  display: grid;
  place-items: center;
  color: white;
  box-shadow: var(--shadow-glow);
}

.brand-name {
  font-size: 22px;
  font-weight: 800;
  color: var(--text-primary);
  letter-spacing: 0.5px;
}

.brand-slogan {
  font-size: 12px;
  color: var(--text-secondary);
}

.brand-hero {
  max-width: 480px;
}

.hero-title {
  font-size: 44px;
  font-weight: 800;
  line-height: 1.2;
  color: var(--text-primary);
  letter-spacing: -1px;
  margin-bottom: var(--space-4);
}

.hero-desc {
  font-size: 15px;
  line-height: 1.8;
  color: var(--text-regular);
  margin-bottom: var(--space-6);
}

.feature-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.feature-item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  font-size: 14px;
  color: var(--text-regular);
}

.fi-icon {
  display: grid;
  place-items: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--brand-gradient);
  color: white;
  font-size: 12px;
  flex-shrink: 0;
}

.brand-footer {
  font-size: 12px;
  color: var(--text-secondary);
}

/* 右侧登录表单 */
.login-pane {
  position: relative;
  z-index: 1;
  display: grid;
  place-items: center;
  padding: var(--space-6);
}

.login-card {
  width: 100%;
  max-width: 400px;
  background: var(--bg-overlay);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-xl);
  padding: var(--space-8);
  box-shadow: var(--shadow-lg);
  position: relative;
}

.login-title {
  font-size: 26px;
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: var(--space-2);
}

.login-sub {
  font-size: 13px;
  color: var(--text-secondary);
  margin-bottom: var(--space-6);
}

.form-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin: var(--space-3) 0 var(--space-5) 0;
  font-size: 12px;
}

.form-tip {
  color: var(--text-secondary);
  font-family: var(--font-mono);
}

.login-btn {
  width: 100%;
  font-weight: 600 !important;
  letter-spacing: 4px;
  font-size: 15px !important;
}

.theme-toggle {
  text-align: center;
  margin-top: var(--space-4);
}

:deep(.el-form-item) {
  margin-bottom: var(--space-4);
}

:deep(.el-form-item__label) {
  font-size: 13px;
  color: var(--text-secondary);
  font-weight: 500;
}

/* 响应式 */
@media (max-width: 960px) {
  .login-page {
    grid-template-columns: 1fr;
  }
  .brand-pane {
    display: none;
  }
}
</style>
