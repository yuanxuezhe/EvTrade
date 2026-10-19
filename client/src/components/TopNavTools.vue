<!--
  TopNavTools.vue — TopNav 右侧工具区 (top-nav-overhaul 2026-10-18, REQ-FE-555)

  从 AppHeader.vue 第 10-77 行整体搬来,保留 6 个工具:
  - RPC 状态 (with tooltip)
  - 交易中 / 休市 (with tradingDate)
  - 总资产 (asset mini)
  - 刷新按钮
  - 主题切换
  - 用户下拉 (含 profile / logout)

  pageTitle/pageSubtitle 段已删 (TopNav 取代导航职责,标题冗余)。
-->
<template>
  <div class="top-nav-tools">
    <!-- RPC 状态 -->
    <el-tooltip :content="`RPC 状态: ${rpcTooltip}`" placement="bottom">
      <div class="rpc-status" :class="rpcClass" data-el="rpc-status-indicator">
        <span class="rpc-dot"></span>
        <span class="rpc-label">{{ rpcLabel }}</span>
      </div>
    </el-tooltip>

    <!-- 行情状态 + 交易日期 -->
    <div class="market-status">
      <span class="status-dot" :class="marketOpen ? 'open' : 'closed'"></span>
      <span class="status-text">{{ marketOpen ? '交易中' : '休市' }}</span>
      <span class="status-time text-mono">{{ tradingDate }}</span>
    </div>

    <!-- 总资产 -->
    <div v-if="assetStore.asset.total_asset > 0" class="asset-mini">
      <div class="mini-label">总资产</div>
      <div class="mini-value gradient-text text-mono">
        ¥{{ formatMoney(assetStore.asset.total_asset) }}
      </div>
    </div>

    <!-- 刷新按钮 -->
    <el-tooltip content="刷新数据" placement="bottom">
      <button class="icon-btn" @click="handleRefresh" :class="{ spinning: refreshing }">
        <el-icon :size="18"><Refresh /></el-icon>
      </button>
    </el-tooltip>

    <!-- 主题切换 -->
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
      <div class="user-chip">
        <div class="avatar" :class="`role-${roleKey}`">
          {{ avatarText }}
        </div>
        <div class="user-meta">
          <div class="user-name">{{ displayName }}</div>
          <div class="user-role">{{ roleLabel }}</div>
        </div>
        <el-icon class="user-arrow"><ArrowDown /></el-icon>
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
          <el-dropdown-item command="logout" divided :icon="SwitchButton">退出登录</el-dropdown-item>
        </el-dropdown-menu>
      </template>
    </el-dropdown>
  </div>
</template>

<script setup>
import { computed, ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus/es'  // REQ-FE-552.2: 子路径避免把整包拽进 deps
import {
  Refresh, Sunny, Moon, User,
  SwitchButton, ArrowDown
} from '@element-plus/icons-vue'
import { useUiStore } from '../stores/ui'
import { useAssetStore } from '../stores/asset'
import { usePositionStore } from '../stores/position'
import { useHoldingsStore } from '../stores/holdings'
import { useAuthStore } from '../stores/auth'
import { useRpcStatusStore } from '../stores/rpc_status'
import { formatMoney } from '../utils/format'
import { api } from '../api'

const router = useRouter()
const uiStore = useUiStore()
const assetStore = useAssetStore()
const positionStore = usePositionStore()
const holdingsStore = useHoldingsStore()
const authStore = useAuthStore()
const rpcStatusStore = useRpcStatusStore()

const refreshing = ref(false)
const tradingDate = computed(() => {
  const d = holdingsStore.activeTrdDate
  if (!d) return ''
  return `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6, 8)}`
})

// 交易时段：以后端 /api/trading/clock 为准（DB 配的 trading_session）
const tradingClock = ref({ is_in_session: false })

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

// RPC 三态: 0=OK 1=通讯异常 2=数据异常
const rpcStatus = computed(() => Number(rpcStatusStore.status ?? 0))
const rpcClass = computed(() => {
  const s = rpcStatus.value
  if (s === 0) return 'ok'
  if (s === 1) return 'comm-error'
  return 'data-error'
})
const rpcLabel = computed(() => {
  const s = rpcStatus.value
  if (s === 0) return 'RPC OK'
  if (s === 1) return 'RPC 异常'
  return 'RPC 数据异常'
})
const rpcTooltip = computed(() => {
  const s = rpcStatus.value
  if (s === 0) return rpcStatusStore.message || 'RPC通讯正常'
  return `${rpcStatusStore.message || '未知状态'} | ${rpcStatusStore.status}`
})

async function _refreshRpcStatusOnce() {
  try {
    const data = await api.getRpcStatus()
    if (data) rpcStatusStore.setFromPayload(data)
  } catch (_) { /* 首屏静默, 后续 ws 推送覆盖 */ }
}

let clockTimer = null
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
  refreshClock()
  clockTimer = setInterval(refreshClock, 30000)
  _refreshRpcStatusOnce()
})

onUnmounted(() => {
  if (clockTimer) clearInterval(clockTimer)
})

async function handleRefresh() {
  refreshing.value = true
  try {
    // 全部走 holdings store 缓存（统一日志 + 加载状态）
    await holdingsStore.refreshAll()
    // 同步刷新 asset/position store（兼容老 view）
    await Promise.allSettled([
      assetStore.fetchAsset(),
      positionStore.fetchPositions()
    ])
    ElMessage.success({ message: '数据已刷新', duration: 1500 })
  } catch (e) {
    // 错误已由 holdings log 记录
  } finally {
    setTimeout(() => (refreshing.value = false), 500)
  }
}

async function handleUserCmd(cmd) {
  if (cmd === 'profile') router.push('/profile')
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
.top-nav-tools {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex-shrink: 0;
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

.rpc-status {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  padding: 4px 10px;
  border-radius: var(--radius-full);
  font-size: 12px;
  font-weight: 600;
  border: 1px solid var(--border-base);
  background: var(--bg-soft);
  transition: background var(--transition-fast);
  cursor: default;
}
.rpc-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--text-secondary);
  flex-shrink: 0;
}
.rpc-status.ok .rpc-dot {
  background: #67c23a;
  box-shadow: 0 0 0 3px rgba(103, 194, 58, 0.18);
}
.rpc-status.comm-error {
  background: rgba(245, 108, 108, 0.12);
  border-color: rgba(245, 108, 108, 0.4);
  color: #c45656;
}
.rpc-status.comm-error .rpc-dot {
  background: #f56c6c;
  box-shadow: 0 0 0 3px rgba(245, 108, 108, 0.2);
  animation: pulse 1.4s infinite;
}
.rpc-status.data-error {
  background: rgba(230, 162, 60, 0.12);
  border-color: rgba(230, 162, 60, 0.4);
  color: #b07b18;
}
.rpc-status.data-error .rpc-dot {
  background: #e6a23c;
  box-shadow: 0 0 0 3px rgba(230, 162, 60, 0.2);
}
.rpc-label {
  white-space: nowrap;
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

@keyframes pulse {
  0%, 100% { transform: scale(1); opacity: 1; }
  50% { transform: scale(1.15); opacity: 0.85; }
}
</style>
