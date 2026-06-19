<template>
  <header class="app-header">
    <div class="header-left">
      <button
        v-if="uiStore.isMobile"
        class="icon-btn hamburger"
        @click="$emit('toggle-sidebar')"
        aria-label="菜单"
      >
        <el-icon :size="20"><Menu /></el-icon>
      </button>

      <div class="page-title" :class="{ 'mobile-only-title': uiStore.isMobile }">
        <span class="title-text">{{ pageTitle }}</span>
        <span v-if="!uiStore.isMobile" class="title-sub">{{ pageSubtitle }}</span>
      </div>
    </div>

    <div class="header-right">
      <div class="market-status">
        <span class="status-dot" :class="marketOpen ? 'open' : 'closed'"></span>
        <span v-if="!uiStore.isMobile" class="status-text">{{ marketOpen ? '交易中' : '休市' }}</span>
        <span class="status-time text-mono">{{ currentTime }}</span>
      </div>

      <div v-if="!uiStore.isMobile && assetStore.asset.total_asset > 0" class="asset-mini">
        <div class="mini-label">总资产</div>
        <div class="mini-value gradient-text text-mono">
          ¥{{ formatMoney(assetStore.asset.total_asset) }}
        </div>
      </div>

      <el-tooltip content="刷新数据" placement="bottom">
        <button class="icon-btn" @click="handleRefresh" :class="{ spinning: refreshing }">
          <el-icon :size="18"><Refresh /></el-icon>
        </button>
      </el-tooltip>

      <el-tooltip :content="uiStore.theme === 'dark' ? '切换浅色' : '切换深色'" placement="bottom">
        <button class="icon-btn" @click="uiStore.toggleTheme">
          <el-icon :size="18">
            <Sunny v-if="uiStore.theme === 'dark'" />
            <Moon v-else />
          </el-icon>
        </button>
      </el-tooltip>

      <!-- 用户下拉 -->
      <el-dropdown trigger="click" @command="handleUserCmd">
        <div class="user-chip" :class="{ 'mobile-chip': uiStore.isMobile }">
          <div class="avatar" :class="`role-${roleKey}`">
            {{ avatarText }}
          </div>
          <div v-if="!uiStore.isMobile" class="user-meta">
            <div class="user-name">{{ displayName }}</div>
            <div class="user-role">{{ roleLabel }}</div>
          </div>
          <el-icon v-if="!uiStore.isMobile" class="user-arrow"><ArrowDown /></el-icon>
        </div>
        <template #dropdown>
          <el-dropdown-menu>
            <div class="user-card">
              <div class="uc-name">{{ displayName }}</div>
              <div class="uc-info">
                <span class="uc-role-tag" :class="`role-${roleKey}`">{{ roleLabel }}</span>
                <span class="uc-username text-mono">@{{ authStore.user?.username }}</span>
              </div>
              <div v-if="authStore.user?.last_login_at" class="uc-last">
                上次登录: {{ formatLastLogin(authStore.user.last_login_at) }}
              </div>
            </div>
            <el-dropdown-item command="profile" :icon="User">个人资料</el-dropdown-item>
            <!-- 修改密码入口在个人资料页, 不再放菜单 -->
            <!-- 用户管理入口在侧栏, 不再重复 -->
            <el-dropdown-item command="logout" divided :icon="SwitchButton">退出登录</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>
  </header>
</template>

<script setup>
import { computed, ref, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Refresh, Sunny, Moon, User, Lock, UserFilled,
  SwitchButton, ArrowDown, Menu
} from '@element-plus/icons-vue'
import { useUiStore } from '../stores/ui'
import { useAssetStore } from '../stores/asset'
import { useOrderStore } from '../stores/order'
import { usePositionStore } from '../stores/position'
import { useHoldingsStore } from '../stores/holdings'
import { useAuthStore } from '../stores/auth'
import { formatMoney } from '../utils/format'
import { api } from '../api'
// 修改密码弹窗已移入 Profile.vue, AppHeader 不再需要

const route = useRoute()
const router = useRouter()
defineEmits(['toggle-sidebar'])
const uiStore = useUiStore()
const assetStore = useAssetStore()
const orderStore = useOrderStore()
const positionStore = usePositionStore()
const holdingsStore = useHoldingsStore()
const authStore = useAuthStore()

const refreshing = ref(false)
const currentTime = ref('')
// 交易时段：以后端 /api/trading/clock 为准（DB 配的 trading_session）
const tradingClock = ref({ is_in_session: false })

const pageMeta = {
  '/': { title: '仪表盘', sub: '账户概览与今日行情' },
  '/positions': { title: '持仓管理', sub: '查看与管理您的持仓' },
  '/trade': { title: '交易下单', sub: '快速下单与今日委托' },
  '/orders': { title: '委托查询', sub: '历史委托记录' },
  '/trades': { title: '成交查询', sub: '历史成交明细' },
  '/asset': { title: '账户资金', sub: '资金详情与资产分布' },
  '/users': { title: '用户管理', sub: '管理系统账号与权限' },
  '/holdings': { title: '持仓查询', sub: '当前账户持仓明细' },
  '/t0-trade': { title: '快速做T', sub: '日内做T开平仓与敞口管理' },
  '/t-strategy': { title: '策略做T', sub: '自动化做T策略 (占位)' },
  '/algo-strategy': { title: '策略交易', sub: '算法交易策略 (占位)' },
  '/system-init': { title: '系统初始化', sub: '交易日 / 行情 / 柜台初始化' },
  '/system-config': { title: '系统配置', sub: '对账 / 推送 / 风险参数配置' },
  '/profile': { title: '个人资料', sub: '查看与编辑个人信息' }
}

const pageTitle = computed(() => pageMeta[route.path]?.title || 'EvTrade')
const pageSubtitle = computed(() => pageMeta[route.path]?.sub || '')

const marketOpen = computed(() => !!tradingClock.value?.is_in_session)

const displayName = computed(
  () => authStore.user?.full_name || authStore.user?.username || '未登录'
)
const roleKey = computed(() => authStore.user?.role || 'viewer')
const roleLabel = computed(() => {
  const map = { admin: '管理员', trader: '交易员', viewer: '只读用户' }
  return map[roleKey.value] || roleKey.value
})
const avatarText = computed(() => {
  const n = displayName.value
  return n ? n.charAt(0).toUpperCase() : '?'
})

let timer = null
let clockTimer = null

function updateTime() {
  const d = new Date()
  const pad = (n) => String(n).padStart(2, '0')
  currentTime.value = `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

async function refreshClock() {
  try {
    tradingClock.value = await api.getTradingClock()
  } catch (_) { /* 静默 */ }
}

function formatLastLogin(iso) {
  const d = new Date(iso)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

onMounted(() => {
  updateTime()
  timer = setInterval(updateTime, 1000)
  refreshClock()
  clockTimer = setInterval(refreshClock, 30000)
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
  if (clockTimer) clearInterval(clockTimer)
})

async function handleRefresh() {
  refreshing.value = true
  try {
    // 全部走 holdings store 缓存（统一日志 + 加载状态）
    await holdingsStore.refreshAll()
    // 同步刷新 order/asset/position store（兼容老 view）
    await Promise.allSettled([
      assetStore.fetchAsset(),
      orderStore.fetchOrders(),
      orderStore.fetchTrades(),
      positionStore.fetchPositions()
    ])
    uiStore.markRefreshed()
    ElMessage.success({ message: '数据已刷新', duration: 1500 })
  } catch (e) {
    // 错误已由 holdings log 记录
  } finally {
    setTimeout(() => (refreshing.value = false), 500)
  }
}

async function handleUserCmd(cmd) {
  if (cmd === 'profile') router.push('/profile')
  else if (cmd === 'users') router.push('/users')
  else if (cmd === 'logout') {
    try {
      await ElMessageBox.confirm('确定要退出登录？', '提示', {
        confirmButtonText: '退出',
        cancelButtonText: '取消',
        type: 'warning'
      })
      await authStore.logout()
      ElMessage.success('已退出登录')
      router.replace('/login')
    } catch {
      // cancelled
    }
  }
}
</script>

<style scoped>
.app-header {
  height: var(--header-height);
  background: var(--bg-elevated);
  border-bottom: 1px solid var(--border-base);
  padding: 0 var(--space-6);
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-shrink: 0;
  backdrop-filter: blur(12px);
  position: relative;
  z-index: 110;  /* 移动端时高于 sidebar-mask(90) 和 sidebar(100) */
  gap: var(--space-3);
}

/* 移动端 */
@media (max-width: 900px) {
  .app-header {
    padding: 0 var(--space-3);
    gap: var(--space-2);
  }
}
.hamburger {
  width: 36px;
  height: 36px;
  display: grid;
  place-items: center;
  background: transparent;
  border: 1px solid var(--border-base);
  border-radius: var(--radius-md);
  color: var(--text-primary);
  cursor: pointer;
  margin-right: var(--space-2);
}
.hamburger:hover {
  background: var(--bg-soft);
}

.page-title {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.title-text {
  font-size: 18px;
  font-weight: 700;
  color: var(--text-primary);
}

.title-sub {
  font-size: 12px;
  color: var(--text-secondary);
}

.header-right {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.market-status {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: 6px 12px;
  background: var(--bg-soft);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-full);
  font-size: 12px;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--color-down);
}

.status-dot.open {
  background: var(--color-down);
  box-shadow: 0 0 0 3px var(--color-down-bg);
  animation: pulse 2s infinite;
}

.status-dot.closed {
  background: var(--text-secondary);
}

.status-text {
  color: var(--text-regular);
  font-weight: 500;
}

.status-time {
  color: var(--text-secondary);
  margin-left: var(--space-2);
  padding-left: var(--space-2);
  border-left: 1px solid var(--border-base);
}

.asset-mini {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  padding: 4px 14px;
  background: var(--brand-gradient-soft);
  border-radius: var(--radius-md);
}

.mini-label {
  font-size: 10px;
  color: var(--text-secondary);
  font-weight: 500;
}

.mini-value {
  font-size: 14px;
  font-weight: 700;
  margin-top: 1px;
}

.icon-btn {
  width: 36px;
  height: 36px;
  display: grid;
  place-items: center;
  background: var(--bg-soft);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-sm);
  color: var(--text-regular);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.icon-btn:hover {
  color: var(--brand-primary);
  border-color: var(--brand-primary);
  background: var(--bg-hover);
}

.icon-btn.spinning .el-icon {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* 用户 chip */
.user-chip {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: 4px 12px 4px 4px;
  background: var(--bg-soft);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-full);
  cursor: pointer;
  transition: all var(--transition-fast);
}
.user-chip.mobile-chip {
  padding: 2px;
  border-radius: 50%;
}

.user-chip:hover {
  border-color: var(--brand-primary);
  background: var(--bg-hover);
}

.avatar {
  width: 30px;
  height: 30px;
  border-radius: 50%;
  color: white;
  display: grid;
  place-items: center;
  font-weight: 700;
  font-size: 13px;
  flex-shrink: 0;
}

.avatar.role-admin { background: var(--brand-gradient); }
.avatar.role-trader { background: var(--color-up-gradient); }
.avatar.role-viewer { background: linear-gradient(135deg, #5fa8ff, #82b9ff); }

.user-meta {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  line-height: 1.2;
}

.user-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.user-role {
  font-size: 10px;
  color: var(--text-secondary);
  margin-top: 1px;
}

.user-arrow {
  color: var(--text-secondary);
  font-size: 12px;
}

/* 下拉 user card */
.user-card {
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--border-light);
  margin-bottom: 4px;
  min-width: 220px;
}

.uc-name {
  font-weight: 600;
  font-size: 14px;
  color: var(--text-primary);
}

.uc-info {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-top: 4px;
}

.uc-role-tag {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: var(--radius-xs);
  font-weight: 600;
  color: white;
}

.uc-role-tag.role-admin { background: var(--brand-gradient); }
.uc-role-tag.role-trader { background: var(--color-up-gradient); }
.uc-role-tag.role-viewer { background: linear-gradient(135deg, #5fa8ff, #82b9ff); }

.uc-username {
  font-size: 11px;
  color: var(--text-secondary);
}

.uc-last {
  font-size: 11px;
  color: var(--text-secondary);
  margin-top: 4px;
}
</style>
