import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { setUnauthorizedHandler } from '../api'

const Login = () => import('../views/Login.vue')
const Dashboard = () => import('../views/Dashboard.vue')
const Trade = () => import('../views/Trade.vue')
const Asset = () => import('../views/Asset.vue')
const Holdings = () => import('../views/Holdings.vue')
// v13 trade-page-redesign-v2: 删除 TodayOrders/TodayTrades view（由 Trade.vue 内嵌 mini-panel 承担）
//   HistoryOrders/Trades 走 HTTP 局部 state（不入 IDB）
const HistoryOrders = () => import('../views/HistoryOrders.vue')
const HistoryTrades = () => import('../views/HistoryTrades.vue')
const AlgoStrategy = () => import('../views/AlgoStrategy.vue')
const TStrategy = () => import('../views/TStrategy.vue')
const StrategyTrade = () => import('../views/StrategyTrade.vue')
const Users = () => import('../views/Users.vue')
const Profile = () => import('../views/Profile.vue')
const SystemInit = () => import('../views/SystemInit.vue')
const SystemConfig = () => import('../views/SystemConfig.vue')
const T0Trade = () => import('../views/T0Trade.vue')
const CacheAsset = () => import('../views/CacheAsset.vue')
const CachePositions = () => import('../views/CachePositions.vue')
const CacheOrders = () => import('../views/CacheOrders.vue')
const CacheTrades = () => import('../views/CacheTrades.vue')
// v21 stock-info-crawler: 股票信息同步管理页面 (admin-only)
const AdminSync = () => import('../views/AdminSync.vue')
// v21 stock-info-crawler: 证券信息设置页面 (admin-only 占位)
const AdminStockConfig = () => import('../views/AdminStockConfig.vue')

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
  // v13 trade-page-redesign-v2: /today/* 路由删除, 改 redirect
  //   HistoryOrders/Trades 走 HTTP 局部 state（不入 IDB）
  { path: '/history/orders', name: 'HistoryOrders', component: HistoryOrders, meta: { title: '历史委托' } },
  { path: '/history/trades', name: 'HistoryTrades', component: HistoryTrades, meta: { title: '历史成交' } },
  // v13: 旧 /orders /trades 路由 redirect 到 history (新入口)
  { path: '/orders', redirect: '/history/orders' },
  { path: '/trades', redirect: '/history/trades' },
  // v13: 老 /today/* 书签兼容 redirect (跳到 history view)
  { path: '/today/orders', redirect: '/history/orders' },
  { path: '/today/trades', redirect: '/history/trades' },
  { path: '/holdings', name: 'Holdings', component: Holdings, meta: { title: '持仓查询' } },
  // /to-management 旧路由 → redirect 到 /t0-trade (T0Trade.vue 真快速做T页面)
  { path: '/to-management', redirect: '/t0-trade' },
  { path: '/t-strategy', name: 'TStrategy', component: TStrategy, meta: { title: '策略做T' } },
  // change strategy_trade task 12: 策略交易视图（trader + admin 可访问）
  { path: '/strategy-trade', name: 'StrategyTrade', component: StrategyTrade, meta: { title: '策略交易', requiresTrader: true } },
  // change strategy_trade task 12: 旧 /algo-strategy 占位页 → 新 /strategy-trade
  //   AlgoStrategy.vue 保留 (其他 view 可能引用), 但路由重定向
  { path: '/algo-strategy', redirect: '/strategy-trade' },
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
  // v21 stock-info-crawler: 股票同步管理 (admin-only, 启动/停止/进度/错误流)
  { path: '/admin/sync', name: 'AdminSync', component: AdminSync, meta: { title: '证券同步', requiresAdmin: true } },
  // v21 stock-info-crawler: 证券信息设置 (admin-only, sync_config 占位)
  { path: '/admin/stock-config', name: 'AdminStockConfig', component: AdminStockConfig, meta: { title: '证券信息设置', requiresAdmin: true } },
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
