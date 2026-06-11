import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { setUnauthorizedHandler } from '../api'

const Login = () => import('../views/Login.vue')
const Dashboard = () => import('../views/Dashboard.vue')
const Position = () => import('../views/Position.vue')
const Trade = () => import('../views/Trade.vue')
const Asset = () => import('../views/Asset.vue')
const Orders = () => import('../views/Orders.vue')
const Holdings = () => import('../views/Holdings.vue')
const Trades = () => import('../views/Trades.vue')
const AlgoStrategy = () => import('../views/AlgoStrategy.vue')
const TStrategy = () => import('../views/TStrategy.vue')
const Users = () => import('../views/Users.vue')
const Profile = () => import('../views/Profile.vue')

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: Login,
    meta: { title: '登录', layout: 'blank', public: true }
  },
  { path: '/', name: 'Dashboard', component: Dashboard, meta: { title: '仪表盘' } },
  { path: '/positions', redirect: '/to-management' },
  { path: '/trade', name: 'Trade', component: Trade, meta: { title: '交易下单', requiresTrader: true } },
  { path: '/asset', name: 'Asset', component: Asset, meta: { title: '账户资金' } },
  { path: '/orders', name: 'Orders', component: Orders, meta: { title: '委托查询' } },
  { path: '/holdings', name: 'Holdings', component: Holdings, meta: { title: '持仓查询' } },
  { path: '/trades', name: 'Trades', component: Trades, meta: { title: '成交查询' } },
  { path: '/to-management', name: 'ToManagement', component: Position, meta: { title: '快速做T' } },
  { path: '/t-strategy', name: 'TStrategy', component: TStrategy, meta: { title: '做T策略' } },
  { path: '/algo-strategy', name: 'AlgoStrategy', component: AlgoStrategy, meta: { title: '交易策略' } },
  {
    path: '/users',
    name: 'Users',
    component: Users,
    meta: { title: '用户管理', requiresAdmin: true }
  },
  { path: '/profile', name: 'Profile', component: Profile, meta: { title: '个人资料' } },
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
