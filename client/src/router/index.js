import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { setUnauthorizedHandler } from '../api/http'

const Login = () => import('../views/Login.vue')
const Dashboard = () => import('../views/Dashboard.vue')
const Trade = () => import('../views/Trade.vue')
const Asset = () => import('../views/Asset.vue')
// 持仓由 Trade.vue 右上 HoldingsPanel 承担 (无独立查询页, HistoryOrders/HistoryTrades view 不存在)
// script-strategy change: 前端编写 Python 脚本 + 回测 + 实盘
const ScriptDev = () => import('../views/ScriptDev.vue')
const ScriptTask = () => import('../views/ScriptTask.vue')
// 策略下单母单管理 (4 面板, 拆 5 子组件, 由 StrategyOrder.vue 编排)
const StrategyOrder = () => import('../views/StrategyOrder.vue')
const Users = () => import('../views/Users.vue')
const Profile = () => import('../views/Profile.vue')
const SystemInit = () => import('../views/SystemInit.vue')
const SystemConfig = () => import('../views/SystemConfig.vue')
const T0Trade = () => import('../views/T0Trade.vue')
const CacheAsset = () => import('../views/CacheAsset.vue')
const CachePositions = () => import('../views/CachePositions.vue')
const CacheOrders = () => import('../views/CacheOrders.vue')
const CacheTrades = () => import('../views/CacheTrades.vue')
// change stock-info-crawler: 证券信息设置页面 (admin-only, 含同步状态/启动, sync_config 占位)
const AdminStockConfig = () => import('../views/AdminStockConfig.vue')
// add-stkpool-module: 证券池 (auth 通用鉴权, 不分 RBAC)
const StkPool = () => import('../views/StkPool.vue')
// stkpool-view-feature: 证券池只读视图 (仪表盘和交易下单之间, 自选用)
const StkPoolView = () => import('../views/StkPoolView.vue')
// his-quote-backfill: 数据补全 → 历史行情补全 (admin-only)
const HistoryQuoteCompletion = () => import('../views/HistoryQuoteCompletion.vue')

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: Login,
    meta: { title: '登录', layout: 'blank', public: true }
  },
  { path: '/', name: 'Dashboard', component: Dashboard, meta: { title: '仪表盘' } },
  // stkpool-view-feature: 仪表盘和交易下单之间插入的只读证券池视图
  { path: '/stkpool-view', name: 'StkPoolView', component: StkPoolView, meta: { title: '自选池' } },
  { path: '/positions', redirect: '/t0-trade' },
  { path: '/trade', name: 'Trade', component: Trade, meta: { title: '交易下单', requiresTrader: true } },
  { path: '/asset', name: 'Asset', component: Asset, meta: { title: '账户资金' } },
  // 持仓由 Trade.vue 右上 HoldingsPanel 承担; 保留 redirect 兼容旧书签
  { path: '/holdings', redirect: '/trade' },
  // /to-management 旧路由 → redirect 到 /t0-trade (T0Trade.vue 真快速做T页面)
  { path: '/to-management', redirect: '/t0-trade' },
  // 旧 /t-strategy 占位页已下线 → 旧书签统一跳快速做T
  { path: '/t-strategy', redirect: '/t0-trade' },
  // script-strategy change: 2 个新页面
  { path: '/script-dev', name: 'ScriptDev', component: ScriptDev, meta: { title: '策略开发', requiresTrader: true } },
  { path: '/script-task', name: 'ScriptTask', component: ScriptTask, meta: { title: '策略运行', requiresTrader: true } },
  // 策略下单母单 (实盘下单入口, 仿 ScriptTask 路由)
  { path: '/strategy-order', name: 'StrategyOrder', component: StrategyOrder, meta: { title: '策略下单', requiresTrader: true } },
  {
    path: '/users',
    name: 'Users',
    component: Users,
    meta: { title: '用户管理', requiresAdmin: true }
  },
  { path: '/profile', name: 'Profile', component: Profile, meta: { title: '个人资料' } },
  { path: '/system-init', name: 'SystemInit', component: SystemInit, meta: { title: '系统初始化', requiresAdmin: true } },
  { path: '/system-config', name: 'SystemConfig', component: SystemConfig, meta: { title: '系统配置' } },  // 允许普通用户查看 (写权限 UI 层控制)
  { path: '/t0-trade', name: 'T0Trade', component: T0Trade, meta: { title: '快速做T' } },
  // admin-only: IDB 4 张业务表的 CRUD 查看器
  { path: '/admin/cache/asset', name: 'CacheAsset', component: CacheAsset, meta: { title: '交易查询: 资金', requiresAdmin: true } },
  { path: '/admin/cache/positions', name: 'CachePositions', component: CachePositions, meta: { title: '交易查询: 持仓', requiresAdmin: true } },
  { path: '/admin/cache/orders', name: 'CacheOrders', component: CacheOrders, meta: { title: '交易查询: 委托', requiresAdmin: true } },
  { path: '/admin/cache/trades', name: 'CacheTrades', component: CacheTrades, meta: { title: '交易查询: 成交', requiresAdmin: true } },
  // change stock-info-crawler: 证券信息设置 (admin-only, 含同步启动/停止/进度, sync_config 占位)
  { path: '/admin/stock-config', name: 'AdminStockConfig', component: AdminStockConfig, meta: { title: '证券信息设置', requiresAdmin: true } },
  // his-quote-backfill: 数据补全 → 历史行情补全 (admin-only)
  { path: '/data-completion/history-quote', name: 'HistoryQuoteCompletion', component: HistoryQuoteCompletion, meta: { title: '历史行情补全', requiresAdmin: true } },
  // add-stkpool-module: 证券池 (auth 通用鉴权, 不分 RBAC)
  { path: '/stkpool', name: 'StkPool', component: StkPool, meta: { title: '证券池' } },
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
