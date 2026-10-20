<!--
  TopNav.vue — 桌面顶部导航 (top-nav-overhaul 2026-10-18, REQ-FE-555)

  5 组下拉 + 移动端隐藏 (mobile 走 BottomNav).

  设计:
  - 独立 5 组信息架构,不复用 PAGE_NAV_TREE (后者是 RBAC 角色管理 UI 单一事实源)
  - 与 PAGE_NAV_TREE 共用 pageKey 命名,RBAC filter 走 authStore.hasPageKey
  - 桌面顶横排,右下顶位挂 AppHeader (App.vue 组合)
-->
<template>
  <header class="top-nav" :class="{ 'is-mobile': uiStore.isMobile }">
    <div class="top-nav-inner">
      <!-- 品牌 logo — 点击回到仪表盘 (top-nav-overhaul 2026-10-18 增强) -->
      <router-link to="/" class="brand" aria-label="回到仪表盘">
        <div class="brand-logo" aria-hidden="true">
          <el-icon :size="22"><TrendCharts /></el-icon>
        </div>
        <div class="brand-text">
          <div class="brand-title">EvTrade</div>
          <div class="brand-sub">智能交易终端</div>
        </div>
      </router-link>

      <!-- 5 组下拉菜单 (RBAC filter 后) -->
      <el-menu
        v-if="visibleGroups.length > 0"
        mode="horizontal"
        :ellipsis="false"
        class="top-menu"
        :default-active="activePath"
        @select="onSelect"
      >
        <el-sub-menu
          v-for="group in visibleGroups"
          :key="group.key"
          :index="group.key"
        >
          <template #title>
            <el-icon v-if="group.icon" :size="16">
              <component :is="group.icon" />
            </el-icon>
            <span>{{ group.label }}</span>
          </template>
          <el-menu-item
            v-for="page in group.pages"
            :key="page.pageKey"
            :index="page.path"
          >
            <el-icon v-if="page.icon" :size="14">
              <component :is="page.icon" />
            </el-icon>
            <span>{{ page.label }}</span>
          </el-menu-item>
        </el-sub-menu>
      </el-menu>

      <!-- 右侧工具区 (由 TopNavTools 接管, 取代 AppHeader 蓝色整条, top-nav-overhaul 2026-10-18) -->
      <TopNavTools class="top-nav-tools-slot" />
    </div>
  </header>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useUiStore } from '../stores/ui'
import { useAuthStore } from '../stores/auth'
import TopNavTools from './TopNavTools.vue'
// top-nav-overhaul 2026-10-18: TopNavTools.vue 接管了原 AppHeader 全部图标,
// TopNav 自己只保留 5 组 + 子页用到的图标
import {
  TrendCharts,           // logo + 「交易」组
  Wallet,                // 「资金」组 + 账户资金页
  EditPen,               // 「策略」组 + 策略开发页
  DataLine,              // 策略运行页
  Setting,               // 「管理」组
  Operation,             // 「系统」组
  DataBoard,             // 证券信息设置页
  Refresh,               // 历史行情补全页 + 刷新按钮已在 TopNavTools
  Tickets,               // 快速做T页
  Star,                  // 自选池页
  Avatar,                // 角色管理页
  Collection,            // 证券池页
  User,                  // 用户管理页 (req-2026-10-19 topnav-icon-completion)
  List,                  // 策略下单母单页 — 母单/单据语义
  Tools,                 // 系统配置页
  Brush,                 // 系统初始化页 — 初始化/重置语义
} from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()
const uiStore = useUiStore()
const authStore = useAuthStore()

// 5 组独立信息架构 (REQ-FE-555)
//   - pageKey 与 PAGE_NAV_TREE 命名一致 (数据维度同一)
//   - 业务展示层独立分组 (TOP-5 列),不复用 RBAC tree 6 业务域
const NAV_GROUPS = [
  {
    key: 'trade',
    label: '交易',
    icon: TrendCharts,
    pages: [
      { pageKey: 'stkpool-view', label: '自选池', path: '/stkpool-view', icon: Star },
      { pageKey: 'trade', label: '交易下单', path: '/trade', icon: TrendCharts },
      { pageKey: 't0-trade', label: '快速做T', path: '/t0-trade', icon: Tickets },
    ],
  },
  {
    key: 'fund',
    label: '资金',
    icon: Wallet,
    pages: [
      { pageKey: 'asset', label: '账户资金', path: '/asset', icon: Wallet },
    ],
  },
  {
    key: 'strategy',
    label: '策略',
    icon: EditPen,
    pages: [
      { pageKey: 'script-dev', label: '策略开发', path: '/script-dev', icon: EditPen },
      { pageKey: 'script-task', label: '策略运行', path: '/script-task', icon: DataLine },
      { pageKey: 'strategy-order', label: '策略下单母单', path: '/strategy-order', icon: List },
    ],
  },
  {
    key: 'admin',
    label: '管理',
    icon: Setting,
    pages: [
      { pageKey: 'users', label: '用户管理', path: '/users', icon: User },
      { pageKey: 'roles', label: '角色管理', path: '/roles', icon: Avatar },
      { pageKey: 'stkpool', label: '证券池', path: '/stkpool', icon: Collection },
    ],
  },
  {
    key: 'system',
    label: '系统',
    icon: Operation,
    pages: [
      { pageKey: 'system-init', label: '系统初始化', path: '/system-init', icon: Brush },
      { pageKey: 'system-config', label: '系统配置', path: '/system-config', icon: Tools },
      { pageKey: 'admin-stock-config', label: '证券信息设置', path: '/admin/stock-config', icon: DataBoard },
      { pageKey: 'data-completion-history-quote', label: '历史行情补全', path: '/data-completion/history-quote', icon: Refresh },
    ],
  },
]

// RBAC filter: 隐藏无权限 pageKey;空组也隐藏
const visibleGroups = computed(() => {
  return NAV_GROUPS
    .map((g) => ({
      ...g,
      pages: g.pages.filter((p) => authStore.hasPageKey(p.pageKey)),
    }))
    .filter((g) => g.pages.length > 0)
})

const activePath = computed(() => route.path)

function onSelect(path) {
  if (path && path !== route.path) {
    router.push(path)
  }
}
</script>

<style scoped>
.top-nav {
  display: flex;
  height: 56px;
  background: var(--bg-elevated);
  border-bottom: 1px solid var(--border-light);
  position: sticky;
  top: 0;
  z-index: 100;
  width: 100%;
  box-sizing: border-box;
}

.top-nav.is-mobile {
  display: none;
}

.top-nav-inner {
  display: flex;
  align-items: center;
  width: 100%;
  height: 100%;
  padding: 0 var(--space-4);
  gap: var(--space-4);
}

.brand {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
  flex-shrink: 0;
}

.brand-logo {
  width: 36px;
  height: 36px;
  border-radius: var(--radius-sm);
  background: var(--brand-gradient);
  display: grid;
  place-items: center;
  color: white;
  box-shadow: var(--shadow-glow);
}

.brand-text {
  display: flex;
  flex-direction: column;
  line-height: 1.1;
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

.top-menu {
  flex: 0 1 auto;
  border-bottom: none !important;
  background: transparent !important;
  height: 100%;
}

.top-menu :deep(.el-sub-menu__title),
.top-menu :deep(.el-menu-item) {
  height: 56px;
  line-height: 56px;
}

.top-nav-spacer {
  /* 已废止 — top-nav-overhaul 2026-10-18: 右侧用 TopNavTools 取代,不再需要 spacer */
}

.top-nav-tools-slot {
  margin-left: auto;
}
</style>
