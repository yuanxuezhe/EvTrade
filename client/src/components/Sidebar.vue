<template>
  <aside class="sidebar">
    <div class="sidebar-brand">
      <div class="brand-logo">
        <el-icon :size="22"><TrendCharts /></el-icon>
      </div>
      <transition name="fade">
        <div v-if="!uiStore.sidebarCollapsed || uiStore.isMobile" class="brand-text">
          <div class="brand-title">EvTrade</div>
          <div class="brand-sub">智能交易终端</div>
        </div>
      </transition>
    </div>

    <nav class="sidebar-nav">
      <template v-for="item in menuItems" :key="item.key || item.path || item.label">
        <div v-if="item.divider" class="nav-divider" :title="item.label">
          <span v-if="!uiStore.sidebarCollapsed || uiStore.isMobile" class="divider-label">
            {{ item.label }}
          </span>
        </div>

        <!-- 普通菜单项 -->
        <router-link
          v-else
          :to="item.path"
          class="nav-item"
          :class="{ active: isActive(item.path) }"
        >
          <span class="nav-icon">
            <el-icon :size="18">
              <component :is="item.icon" />
            </el-icon>
          </span>
          <transition name="fade">
            <span v-if="!uiStore.sidebarCollapsed || uiStore.isMobile" class="nav-label">
              {{ item.label }}
            </span>
          </transition>
          <span v-if="(!uiStore.sidebarCollapsed || uiStore.isMobile) && item.badge" class="nav-badge">
            {{ item.badge }}
          </span>
        </router-link>
      </template>
    </nav>

    <div v-if="!uiStore.isMobile" class="sidebar-footer">
      <button class="footer-btn" @click="uiStore.toggleSidebar">
        <el-icon :size="18">
          <Fold v-if="!uiStore.sidebarCollapsed" />
          <Expand v-else />
        </el-icon>
        <transition name="fade">
          <span v-if="!uiStore.sidebarCollapsed">收起菜单</span>
        </transition>
      </button>
    </div>
  </aside>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useUiStore } from '../stores/ui'
import {
  Odometer, Wallet, Money, DataAnalysis, Tickets,
  Fold, Expand, TrendCharts, UserFilled, Files,
  Coin, Cpu, Setting, Operation, Box, Document, Refresh, DataBoard,
  EditPen, DataLine, Collection,
} from '@element-plus/icons-vue'
import { useAuthStore } from '../stores/auth'

const route = useRoute()
const uiStore = useUiStore()
const authStore = useAuthStore()

// v13 trade-page-redesign-v2: pendingCount badge 删除
//   旧实现读 holdings.orders + 老本地 status 码 (pre-existing bug, 'pending'/'partial' 不在 broker 字典)
//   替代: AppHeader 已有总持仓 badge; ws push 实时反映 status 变化
const menuItems = computed(() => {
  const base = [
    { path: '/', label: '仪表盘', icon: Odometer },
    { path: '/trade', label: '交易下单', icon: TrendCharts },
    { divider: true, label: '策略交易' },
    // Sidebar 入口: 真正指向 /t0-trade (T0Trade.vue)
// 路由 /to-management 改 redirect 到 /t0-trade (兼容旧书签)
    { path: '/t0-trade', label: '快速做T', icon: Coin },
    // script-strategy change: 2 个新入口 (前端写脚本 + 跑任务)
    { path: '/script-dev', label: '策略开发', icon: EditPen },
    { path: '/script-task', label: '策略运行', icon: DataLine },
    // v126: 策略下单母单 (实盘下单入口)
    { path: '/strategy-order', label: '策略下单', icon: DataAnalysis },
    // v21 stock-info-crawler: 基础信息分类 (admin-trader 共享入口)
    { divider: true, label: '基础信息' },
    { path: '/admin/stock-config', label: '证券信息', icon: DataBoard },
    // add-stkpool-module: 证券池 (与"证券信息"同级别顶级项, 紧跟其后, auth 通用鉴权)
    { path: '/stkpool', label: '证券池', icon: Collection }
  ]
  if (authStore.isAdmin) {
    base.push({ divider: true, label: '系统管理' })
    base.push({ path: '/system-init', label: '系统初始化', icon: Setting })
    base.push({ path: '/system-config', label: '系统配置', icon: Operation })
    base.push({ path: '/users', label: '用户管理', icon: UserFilled })
    base.push({ divider: true, label: '交易查询' })
    base.push({ path: '/admin/cache/asset', label: '资金查询', icon: Wallet })
    base.push({ path: '/admin/cache/positions', label: '持仓查询', icon: Box })
    base.push({ path: '/admin/cache/orders', label: '委托查询', icon: Tickets })
    base.push({ path: '/admin/cache/trades', label: '成交查询', icon: Document })
  }
  return base
})

function isActive(path) {
  if (path === '/') return route.path === '/'
  // 严格前缀匹配：path 必须等于 route.path 或以 'path/' 开头
  // 避免 /trade 误匹配 /trades（V7 修复）
  return route.path === path || route.path.startsWith(path + '/')
}
</script>

<style scoped>
.sidebar {
  background: var(--bg-elevated);
  border-right: 1px solid var(--border-base);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  transition: width var(--transition-base);
}

.sidebar-brand {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-5) var(--space-4);
  border-bottom: 1px solid var(--border-light);
  min-height: var(--header-height);
}

.brand-logo {
  width: 36px;
  height: 36px;
  border-radius: var(--radius-sm);
  background: var(--brand-gradient);
  display: grid;
  place-items: center;
  color: white;
  flex-shrink: 0;
  box-shadow: var(--shadow-glow);
}

.brand-text {
  overflow: hidden;
  white-space: nowrap;
}

.brand-title {
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
  letter-spacing: 0.5px;
}

.brand-sub {
  font-size: 11px;
  color: var(--text-secondary);
  margin-top: 2px;
}

.sidebar-nav {
  flex: 1;
  padding: var(--space-3) var(--space-3);
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: 10px var(--space-3);
  border-radius: var(--radius-sm);
  color: var(--text-regular);
  text-decoration: none;
  font-size: 14px;
  font-weight: 500;
  transition: all var(--transition-fast);
  position: relative;
  white-space: nowrap;
}

.nav-item:hover {
  background: var(--bg-hover);
  color: var(--brand-primary);
}

.nav-divider {
  margin: var(--space-3) var(--space-2) var(--space-2);
  padding: 0 var(--space-2);
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.nav-divider::before,
.nav-divider::after {
  content: '';
  flex: 1;
  height: 1px;
  background: var(--border-light);
}

.divider-label {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 1px;
  color: var(--text-placeholder);
  text-transform: uppercase;
}

.sidebar-nav.collapsed .nav-divider {
  margin: var(--space-3) auto;
  width: 24px;
}

.nav-item.active {
  background: var(--brand-gradient-soft);
  color: var(--brand-primary);
}

.nav-item.active::before {
  content: '';
  position: absolute;
  left: -12px;
  top: 50%;
  transform: translateY(-50%);
  width: 3px;
  height: 18px;
  border-radius: 0 3px 3px 0;
  background: var(--brand-gradient);
}

.nav-icon {
  display: grid;
  place-items: center;
  flex-shrink: 0;
}

.nav-label {
  flex: 1;
  overflow: hidden;
}

.nav-badge {
  background: var(--color-up-gradient);
  color: white;
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: var(--radius-full);
  min-width: 20px;
  text-align: center;
}

.sidebar-footer {
  padding: var(--space-3);
  border-top: 1px solid var(--border-light);
}

.footer-btn {
  width: 100%;
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: 10px var(--space-3);
  border: none;
  background: transparent;
  color: var(--text-secondary);
  border-radius: var(--radius-sm);
  font-size: 13px;
  cursor: pointer;
  transition: all var(--transition-fast);
  white-space: nowrap;
}

.footer-btn:hover {
  background: var(--bg-hover);
  color: var(--brand-primary);
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 150ms;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
