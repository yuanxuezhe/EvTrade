<template>
  <div v-if="isBlankLayout" class="blank-layout">
    <router-view />
  </div>

  <template v-else>
    <div class="app-layout" :class="{ collapsed: uiStore.sidebarCollapsed }">
      <Sidebar />
      <div class="app-main">
        <AppHeader />
        <main class="app-content">
          <router-view v-slot="{ Component, route }">
            <transition name="page" mode="out-in">
              <component :is="Component" :key="route.fullPath" />
            </transition>
          </router-view>
        </main>
      </div>
    </div>
    <!-- 页面底部固定操作记录栏（贴底 fixed） -->
    <OperationLog v-if="authStore.isAuthenticated" />
  </template>
</template>

<script setup>
import { computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import Sidebar from './components/Sidebar.vue'
import AppHeader from './components/AppHeader.vue'
import OperationLog from './components/OperationLog.vue'
import { useUiStore } from './stores/ui'
import { useAuthStore } from './stores/auth'
import { useWsStore } from './stores/ws'
import { useHoldingsStore } from './stores/holdings'

const route = useRoute()
const uiStore = useUiStore()
const authStore = useAuthStore()
const wsStore = useWsStore()
const holdingsStore = useHoldingsStore()

const isBlankLayout = computed(() => route.meta?.layout === 'blank')

onMounted(async () => {
  // 启动时刷新当前用户信息（若有 token）
  if (authStore.token && !authStore.user) {
    await authStore.fetchMe()
  }
  if (authStore.isAuthenticated) {
    // App 启动：拉取资金 + 持仓 + 委托 + 成交 缓存，启动 ws，启动实时市值 watcher
    holdingsStore.bootstrap()
  }
})

// 登录 / 登出时建立 / 断开 WS 订阅 + 重建 holdings 缓存
watch(
  () => authStore.isAuthenticated,
  async (yes) => {
    if (yes) {
      holdingsStore._startWatchers()
      await holdingsStore.bootstrap()
    } else {
      holdingsStore._stopWatchers()
      wsStore.disconnect()
    }
  }
)
</script>

<style>
.blank-layout {
  width: 100vw;
  height: 100vh;
}

.app-layout {
  display: grid;
  grid-template-columns: var(--sidebar-width) 1fr;
  height: 100vh;
  width: 100vw;
  background: var(--bg-base);
  transition: grid-template-columns var(--transition-base);
}

.app-layout.collapsed {
  grid-template-columns: var(--sidebar-collapsed-width) 1fr;
}

.app-main {
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
}

.app-content {
  flex: 1;
  overflow: auto;
  padding: var(--space-6);
  /* 给底部固定操作记录栏留出空间（折叠态 44px） */
  padding-bottom: 60px;
}

/* 页面切换动画 */
.page-enter-active,
.page-leave-active {
  transition: opacity 200ms, transform 200ms;
}
.page-enter-from {
  opacity: 0;
  transform: translateY(8px);
}
.page-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}
</style>
