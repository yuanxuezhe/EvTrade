import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { setUnauthorizedHandler } from '../api'

const Login = () => import('../views/Login.vue')
const Dashboard = () => import('../views/Dashboard.vue')
const Trade = () => import('../views/Trade.vue')
const Asset = () => import('../views/Asset.vue')
const Holdings = () => import('../views/Holdings.vue')
// v12: 当日 / 历史 拆分 — TodayOrders/Trades 读 Pinia + IDB（无 HTTP）,
//   HistoryOrders/Trades 走 HTTP 局部 state（不入 IDB）
const TodayOrders = () => import('../views/TodayOrders.vue')
const TodayTrades = () => import('../views/TodayTrades.vue')
const HistoryOrders = () => import('../views/HistoryOrders.vue')
const HistoryTrades = () => import('../views/HistoryTrades.vue')
const AlgoStrategy = () => import('../views/AlgoStrategy.vue')
const TStrategy = () => import('../views/TStrategy.vue')
const Users = () => import('../views/Users.vue')
const Profile = () => import('../views/Profile.vue')
const SystemInit = () => import('../views/SystemInit.vue')
const SystemConfig = () => import('../views/SystemConfig.vue')
const T0Trade = () => import('../views/T0Trade.vue')
const CacheAsset = () => import('../views/CacheAsset.vue')
const CachePositions = () => import('../views/CachePositions.vue')
const CacheOrders = () => import('../views/CacheOrders.vue')
const CacheTrades = () => import('../views/CacheTrades.vue')

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: Login,
    meta: { title: '登录', layout: 'blank', public: true }
  },
  { path: '/', name: 'Dashboard', component: Dashboard, meta: { title: '仪表盘' } },
  { path: '/positions', redirect: '/t0-trade' },
  { path: '/trade', name: 'Trade', component: Trade, meta: { title: '交易下单', requiresTrader: true } },
  { path: '/asset', name: 'Asset', component: Asset, meta: { title: '账户资金' } },
  // v12: 委托 / 成交 拆分当日 + 历史 2 套视图
  { path: '/today/orders', name: 'TodayOrders', component: TodayOrders, meta: { title: '当日委托' } },
  { path: '/today/trades', name: 'TodayTrades', component: TodayTrades, meta: { title: '当日成交' } },
  { path: '/history/orders', name: 'HistoryOrders', component: HistoryOrders, meta: { title: '历史委托' } },
  { path: '/history/trades', name: 'HistoryTrades', component: HistoryTrades, meta: { title: '历史成交' } },
  // v12: 旧 /orders /trades 路由 redirect 到 today（同义, 旧书签不破）
  { path: '/orders', redirect: '/today/orders' },
  { path: '/trades', redirect: '/today/trades' },
  { path: '/holdings', name: 'Holdings', component: Holdings, meta: { title: '持仓查询' } },
  // /to-management 旧路由 → redirect 到 /t0-trade (T0Trade.vue 真快速做T页面)
  { path: '/to-management', redirect: '/t0-trade' },
  { path: '/t-strategy', name: 'TStrategy', component: TStrategy, meta: { title: '策略做T' } },
  { path: '/algo-strategy', name: 'AlgoStrategy', component: AlgoStrategy, meta: { title: '策略交易' } },
  {
    path: '/users',
    name: 'Users',
    component: Users,
    meta: { title: '用户管理', requiresAdmin: true }
  },
  { path: '/profile', name: 'Profile', component: Profile, meta: { title: '个人资料' } },
  { path: '/system-init', name: 'SystemInit', component: SystemInit, meta: { title: '系统初始化', requiresAdmin: true } },
  { path: '/system-config', name: 'SystemConfig', component: SystemConfig, meta: { title: '系统配置', requiresAdmin: true } },
  { path: '/t0-trade', name: 'T0Trade', component: T0Trade, meta: { title: '快速做T' } },
  // admin-only: IDB 4 张业务表的 CRUD 查看器
  { path: '/admin/cache/asset', name: 'CacheAsset', component: CacheAsset, meta: { title: '缓存: 资金', requiresAdmin: true } },
  { path: '/admin/cache/positions', name: 'CachePositions', component: CachePositions, meta: { title: '缓存: 持仓', requiresAdmin: true } },
  { path: '/admin/cache/orders', name: 'CacheOrders', component: CacheOrders, meta: { title: '缓存: 委托', requiresAdmin: true } },
  { path: '/admin/cache/trades', name: 'CacheTrades', component: CacheTrades, meta: { title: '缓存: 成交', requiresAdmin: true } },
  { path: '/:pathMatch(.*)*', redirect: '/' }
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior() {
    return { top: 0 }
  }
})

router.beforeEach(async (to) => {
  if (to.meta?.title) {
    document.title = `${to.meta.title} · EvTrade`
  }

  const auth = useAuthStore()

  // 已登录用户访问 /login 时直接回首页
  if (to.meta?.public) {
    if (auth.isAuthenticated && to.path === '/login') {
      return { path: '/' }
    }
    return true
  }

  // 未登录 → 登录页
  if (!auth.isAuthenticated) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }

  // admin only
  if (to.meta?.requiresAdmin && !auth.isAdmin) {
    return { path: '/' }
  }

  // trader (admin or trader)
  if (to.meta?.requiresTrader && !auth.isTrader) {
    return { path: '/' }
  }

  return true
})

// 全局 401 → 跳登录
setUnauthorizedHandler(() => {
  const auth = useAuthStore()
  auth.clear()
  if (router.currentRoute.value.path !== '/login') {
    router.replace({ path: '/login', query: { redirect: router.currentRoute.value.fullPath } })
  }
})

export default router
