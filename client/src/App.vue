<template>
  <div v-if="isBlankLayout" class="blank-layout">
    <router-view />
  </div>

  <template v-else>
    <div
      class="app-layout"
      :class="{
        collapsed: !uiStore.isMobile && uiStore.sidebarCollapsed,
        'is-mobile': uiStore.isMobile,
        'sidebar-open': uiStore.mobileSidebarOpen
      }"
    >
      <!-- 移动端遮罩 -->
      <div v-if="uiStore.isMobile && uiStore.mobileSidebarOpen" class="sidebar-mask" @click="uiStore.toggleSidebar"></div>

      <Sidebar />
      <div class="app-main">
        <AppHeader @toggle-sidebar="onToggleSidebar" />
        <main class="app-content">
          <router-view v-slot="{ Component, route }">
            <transition name="page" mode="out-in">
              <component :is="Component" :key="route.fullPath" />
            </transition>
          </router-view>
        </main>
      </div>
    </div>
    <!-- 页面底部固定操作记录栏（贴底 fixed）
         v-model:expanded 共享给 uiStore,让其它视图（如 Trade.vue）能跟随高度变化 -->
    <OperationLog
      v-if="authStore.isAuthenticated"
      v-model:expanded="uiStore.oplogExpanded"
    />
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
import { useStocksStore } from './stores/stocks'

const route = useRoute()
const uiStore = useUiStore()
const authStore = useAuthStore()
const wsStore = useWsStore()
const holdingsStore = useHoldingsStore()
const stocksStore = useStocksStore()

const isBlankLayout = computed(() => route.meta?.layout === 'blank')

function onToggleSidebar() {
  uiStore.toggleSidebar()
}

// 路由切换时关闭移动端抽屉
watch(
  () => route.fullPath,
  () => {
    if (uiStore.isMobile) uiStore.toggleSidebar()
  }
)

onMounted(async () => {
  // 启动时刷新当前用户信息（若有 token）
  if (authStore.token && !authStore.user) {
    await authStore.fetchMe()
  }
  if (authStore.isAuthenticated) {
    // App 启动：拉取资金 + 持仓 + 委托 + 成交 缓存，启动 ws，启动实时市值 watcher
    holdingsStore.bootstrap()
    // v26: 后台异步预加载 stocks 全量缓存 (~18s)
    // - 不阻塞首屏渲染 (fire-and-forget)
    // - 多个页面 (Trade / T0 / Strategy / Admin) 共享同一 cache
    // - loadCache() 内置 cacheLoading 防重入，重复触发安全
    stocksStore.loadCache().catch((e) => {
      console.warn('[App.vue] stocksStore.loadCache 失败:', e?.message || e)
    })
  }
})

// 登录 / 登出时建立 / 断开 WS 订阅 + 重建 holdings 缓存
watch(
  () => authStore.isAuthenticated,
  async (yes) => {
    if (yes) {
      holdingsStore._startWatchers()
      await holdingsStore.bootstrap()
      // v26: 登录后立即预加载 stocks cache (用户登录后多半会去 Trade/T0/Strategy 下单)
      stocksStore.loadCache().catch((e) => {
        console.warn('[App.vue] stocksStore.loadCache 失败:', e?.message || e)
      })
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

/* 移动端：单列 + Sidebar 抽屉 */
.app-layout.is-mobile {
  grid-template-columns: 1fr;
}
.app-layout.is-mobile .sidebar {
  position: fixed;
  top: 0;
  left: 0;
  height: 100vh;
  width: 80vw;
  max-width: 280px;
  z-index: 95;  /* 桌面侧栏 100 < 移动端 95 = header 110 之下；mask 90 之下 */
  transform: translateX(-100%);
  transition: transform 0.25s ease;
  box-shadow: 0 0 0 transparent;
}
.app-layout.is-mobile.sidebar-open .sidebar {
  transform: translateX(0);
  box-shadow: 4px 0 20px rgba(0, 0, 0, 0.15);
}
.app-layout.is-mobile.sidebar-open {
  grid-template-columns: 1fr; /* main 区不偏移 */
}
.app-layout.is-mobile .app-main {
  width: 100vw;
}

/* 移动端遮罩 */
.sidebar-mask {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
  z-index: 90;
  animation: maskIn 0.2s ease;
}
@keyframes maskIn {
  from { opacity: 0; }
  to   { opacity: 1; }
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
  -webkit-overflow-scrolling: touch;
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
