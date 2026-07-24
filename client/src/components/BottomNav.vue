<!--
  BottomNav.vue — 手机端底部导航栏 + 子标签栏

  经典移动端 Tab 布局:
    底部: 5-6 个常用入口横排
    点击后直接跳转路由

  入口选择 (移动端最常用的 5 个):
    首页 / 交易 / 做T / 历史 / 策略 (管理仅 admin)
-->
<template>
  <nav class="bottom-nav">
    <router-link
      v-for="item in visibleItems"
      :key="item.path"
      :to="item.path"
      class="nav-tab"
      :class="{ active: isActive(item.path) }"
    >
      <el-icon :size="20">
        <component :is="item.icon" />
      </el-icon>
      <span class="tab-label">{{ item.label }}</span>
    </router-link>
  </nav>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import {
  Odometer, TrendCharts, Coin, List, Cpu, Setting
} from '@element-plus/icons-vue'
import { useAuthStore } from '../stores/auth'

const route = useRoute()
const authStore = useAuthStore()

const allItems = [
  { path: '/', label: '首页', icon: Odometer },
  { path: '/trade', label: '交易', icon: TrendCharts },
  { path: '/t0-trade', label: '做T', icon: Coin },
  { path: '/orders', label: '历史', icon: List },
  { path: '/strategy-trade', label: '策略', icon: Cpu },
  { path: '/system-config', label: '管理', icon: Setting, adminOnly: true },
]

const visibleItems = computed(() =>
  allItems.filter((item) => !item.adminOnly || authStore.isAdmin)
)

function isActive(path) {
  if (path === '/') return route.path === '/'
  return route.path === path || route.path.startsWith(path + '/')
}
</script>

<style scoped>
.bottom-nav {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  height: 56px;
  background: var(--bg-elevated);
  border-top: 1px solid var(--border-base);
  display: flex;
  align-items: center;
  z-index: 200;
  padding-bottom: env(safe-area-inset-bottom, 0);
}

.nav-tab {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  padding: 6px 8px;
  color: var(--text-secondary);
  text-decoration: none;
  font-size: 10px;
  font-weight: 500;
  transition: color var(--transition-fast);
  flex: 1;
  min-height: 56px;
  justify-content: center;
}

.nav-tab.active {
  color: var(--brand-primary);
}

.nav-tab.active .el-icon {
  transform: scale(1.1);
  transition: transform 0.2s ease;
}

.tab-label {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
