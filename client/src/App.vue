<template>
  <!-- 启动屏障 — 在 hydrate 完成前显示 loading, 避免首轮 beforeEach 读不到 token 误跳 /login -->
  <div v-if="!authStore.ready" class="app-bootstrap">
    <div class="app-bootstrap-spinner">加载中...</div>
  </div>

  <div v-else-if="isBlankLayout" class="blank-layout">
    <router-view />
  </div>

  <template v-else>
    <div
      class="app-layout"
      :class="{ 'is-mobile': uiStore.isMobile }"
    >
      <TopNav v-if="!uiStore.isMobile" />

      <div class="app-main">
        <AppHeader />
        <main class="app-content">
          <router-view v-slot="{ Component, route: r }">
            <transition name="page" mode="out-in">
              <component :is="Component" :key="r.fullPath" />
            </transition>
          </router-view>
        </main>
      </div>
    </div>
    <!-- 页面底部固定操作记录栏（贴底 fixed）
         v-model:expanded 共享给 uiStore,让其它视图（如 Trade.vue）能跟随高度变化 -->
    <OperationLog
      v-if="authStore.isAuthenticated && !uiStore.isMobile"
      v-model:expanded="uiStore.oplogExpanded"
    />
    <BottomNav
      v-if="authStore.isAuthenticated && uiStore.isMobile"
    />
    </template>
  </template>

<script setup>
import { computed, defineAsyncComponent, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
// REQ-FE-552.1: layout 4 组件 (Sidebar/AppHeader/OperationLog/BottomNav) 改异步加载,
//   首屏主图 (HTML+main+App.vue) 砍 ~50 KB, 组件 fetch 时机延后到 v-if=true 后.
//   v-if 在 App.vue template 已有 (OperationLog/BottomNav 按 auth+ui 状态控制),
//   Sidebar/AppHeader 大多路由都需, 但 setup-parse 仍走 async chunk 拉取,
//   配合 setup 顶层 await / Pinia 屏障 hydrate 整体不阻塞首帧布局.
const TopNav = defineAsyncComponent(() => import('./components/TopNav.vue'))
const AppHeader = defineAsyncComponent(() => import('./components/AppHeader.vue'))
const OperationLog = defineAsyncComponent(() => import('./components/OperationLog.vue'))
const BottomNav = defineAsyncComponent(() => import('./components/BottomNav.vue'))
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

// route 在 setup 阶段可能尚未初始化 (router.install 是异步),
//   route.fullPath undefined → TypeError。可选链 + flush:post 兜底
// (top-nav-overhaul 2026-10-18: 已无 sidebar/抽屉,路由切换不再触发 uiStore.toggleSidebar)

onMounted(async () => {
  // 启动屏障 — 从 IDB 恢复 token 到内存
  // 必须 await hydrate 完成, 否则 router 首轮 beforeEach 读不到 token 误跳 /login
  // 关键: 此 onMounted 在 setup 阶段同步回调, 有 effect scope, 调用 useAuthStore()
  // 不会 'no active Pinia' (与 main.js 顶层 module scope 不同)
  if (!authStore.ready) {
    try {
      await authStore.hydrate()
    } catch (e) {
      console.warn('[App.vue] auth.hydrate failed:', e?.message || e)
    }
  }

  // 启动时刷新当前用户信息（若有 token）
  if (authStore.token && !authStore.user) {
    await authStore.fetchMe()
  }
  if (authStore.isAuthenticated) {
    // App 启动：拉取资金 + 持仓 + 委托 + 成交 缓存，启动 ws，启动实时市值 watcher
    // 刷新后 token 已持久化 → isAuthenticated 初始即 true → 下方 auth watch
    //   (非 immediate) 不触发 → 必须在此显式启动 watcher, 否则 day_pnl recompute 不跑
    holdingsStore._startWatchers()
    holdingsStore.bootstrap()
    // stocks cache 为 IDB 持久化 + Map 索引
    // - initCache() 先从 IDB 秒载 (F5 不再拉后端)
    // - IDB 空 (首次) 才阻塞拉 /stocks/all; 否则后台静默刷新
    stocksStore.initCache().catch((e) => {
      console.warn('[App.vue] stocksStore.initCache 失败:', e?.message || e)
    })
  }
  // 无 /auth/heartbeat 30s 定时器
  //   token 过期由 WS idle 机制处理: 客户端 WS 30s ping + 后端 10 分钟独立 idle 计时 (server/ws/endpoint.py WS_IDLE_TIMEOUT)
})

// 登录 / 登出时建立 / 断开 WS 订阅 + 重建 holdings 缓存
watch(
  () => authStore.isAuthenticated,
  async (yes) => {
    if (yes) {
      holdingsStore._startWatchers()
      await holdingsStore.bootstrap()
      // 登录后立即预加载 stocks cache (IDB 秒载 -> 后台静默 refresh)
      stocksStore.initCache().catch((e) => {
        console.warn('[App.vue] stocksStore.initCache 失败:', e?.message || e)
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

/* 启动屏障 — 全屏 loading, 避免首轮 beforeEach 误跳 /login */
.app-bootstrap {
  width: 100vw;
  height: 100vh;
  display: grid;
  place-items: center;
  background: var(--bg-base);
}
.app-bootstrap-spinner {
  font-size: 14px;
  color: var(--text-secondary);
  padding: 12px 20px;
  background: var(--bg-elevated);
  border-radius: var(--radius-md);
  border: 1px solid var(--border-base);
}

.app-layout {
  display: flex;
  flex-direction: column;
  height: 100vh;
  width: 100vw;
  background: var(--bg-base);
  min-width: 0;
  overflow: hidden;
}

/* 移动端: 单列,顶部 TopNav 隐藏,底部 BottomNav 顶上 */
.app-layout.is-mobile {
  flex-direction: column;
}

/* mobile 不再需要 sidebar 抽屉 CSS — sidebar 已废止
   保留空规则占位以防 hot reload 缓存 (2026-10-18 top-nav-overhaul)
*/
.app-main {
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
  flex: 1;
  height: 100%;
}

.app-content {
  flex: 1;
  overflow: auto;
  padding: var(--space-6);
  /* 给底部固定操作记录栏留出空间（折叠态 44px） */
  padding-bottom: 60px;
  -webkit-overflow-scrolling: touch;
}

/* 移动端: 给底部导航栏留空间 (56px nav + 16px buffer) */
.app-layout.is-mobile .app-content {
  padding: var(--space-3);
  padding-bottom: 72px;
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
