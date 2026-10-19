import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { authApi } from '../api'
import { tokenStorage } from '../api/http'
import { loadSession, saveSession, clearSession } from './auth_idb'

const USER_KEY = 'evtrade-user'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(tokenStorage.get() || '')
  const user = ref(loadUser())
  const loading = ref(false)
  // IDB 持久化 + 启动屏障相关状态
  const ready = ref(false)
  const hydratePromise = ref(null)

  function loadUser() {
    try {
      const raw = localStorage.getItem(USER_KEY)
      return raw ? JSON.parse(raw) : null
    } catch {
      return null
    }
  }

  function saveUser(u) {
    user.value = u
    if (u) localStorage.setItem(USER_KEY, JSON.stringify(u))
    else localStorage.removeItem(USER_KEY)
  }

  const isAuthenticated = computed(() => !!token.value && !!user.value)
  const isAdmin = computed(() => user.value?.role === 'admin')
  const isTrader = computed(() => user.value?.role === 'admin' || user.value?.role === 'trader')
  const isViewer = computed(() => user.value?.role === 'viewer')

  // ── RBAC (rbac-roles-module 2026-09-21) ────────────────────────────────────
  // user.value.roles = [{id,name,display_name,is_builtin,page_keys}, ...]
  // 由 /api/auth/me 返回; 保留旧 isAdmin/isTrader (向后兼容 Sidebar/BottomNav)
  const userRoles = computed(() => user.value?.roles || [])
  const roleNames = computed(() => userRoles.value.map((r) => r.name))
  /** 用户所有 page_keys 的并集; 任一 role 含 '*' → {'*'} */
  const pageKeys = computed(() => {
    const set = new Set()
    for (const r of userRoles.value) {
      for (const k of r.page_keys || []) set.add(k)
    }
    if (set.has('*')) return new Set(['*'])
    return set
  })
  /**
   * 单 page_key 判定; '*' 通配返回 true
   * 向后兼容: 当 user.roles 不存在 (旧 store / fetchMe 未回) 时, fallback 到 isAdmin/isTrader:
   *   - isAdmin=true → 全 page_key 通过 (兼容老 admin 字符串用户)
   *   - isTrader=true → 仅 trader 类 page_key 通过 (dashboard/asset/trade/...)
   *   - 其它 → 不通过 (viewer 默认)
   */
  function hasPageKey(key) {
    const ks = pageKeys.value
    if (ks.size > 0) {
      // RBAC 路径生效
      if (ks.has('*')) return true
      return ks.has(key)
    }
    // 向后兼容 fallback: 老 store / user 无 roles 字段
    if (isAdmin.value) return true  // 老 admin 用户全通
    if (isTrader.value) {
      const TRADER_KEYS = ['dashboard', 'asset', 'trade', 't0-trade', 'strategy-order',
        'script-dev', 'script-task', 'stkpool', 'stkpool-view',
        'cache-asset', 'cache-positions', 'cache-orders', 'cache-trades', 'profile']
      return TRADER_KEYS.includes(key)
    }
    if (isViewer.value) {
      const VIEWER_KEYS = ['dashboard', 'asset', 'cache-orders', 'cache-trades', 'cache-positions', 'profile']
      return VIEWER_KEYS.includes(key)
    }
    return false
  }

  /**
   * 启动屏障 — 从 IDB 恢复 session 到内存 + localStorage
   * 必须在 main.js 中 router 安装前 await 完成, 避免首轮守卫读不到 token 误跳 /login
   * 单例 hydratePromise: 多次调用只初始化一次
   */
  async function hydrate() {
    if (ready.value) return
    if (hydratePromise.value) return hydratePromise.value
    hydratePromise.value = (async () => {
      try {
        const session = await loadSession()
        if (session?.token) {
          token.value = session.token
          tokenStorage.set(session.token)
          if (session.user) saveUser(session.user)
        }
      } catch (e) {
        // loadSession 内部已 swallow; 这里兜底
        console.warn('[auth] hydrate failed:', e?.message || e)
      } finally {
        ready.value = true
      }
    })()
    return hydratePromise.value
  }

  /**
   * REQ-FE-556 (frontend-initial-load-perf 2026-10-18): 共享 ready Promise.
   * - 若 ready 已 true → 立即 resolve (Promise.resolve())
   * - 若 hydrate 未启动 → 启动并返回共享 promise
   * - 若 hydrate 已完成 → 返回其 promise
   * 用法: router.beforeEach(async () => { await auth.ensureReady() ... })
   * 保证后续路由判断时 token 已从 IDB 读完, 不再误跳 /login
   */
  function ensureReady() {
    if (ready.value) return Promise.resolve()
    if (hydratePromise.value) return hydratePromise.value
    return hydrate()
  }

  async function login(username, password) {
    loading.value = true
    try {
      const res = await authApi.login(username, password)
      token.value = res.access_token
      tokenStorage.set(res.access_token)
      saveUser(res.user)
      // 持久化到 IDB（fire-and-forget, 不阻塞登录返回）
      saveSession({ token: res.access_token, user: res.user }).catch((e) => {
        console.warn('[auth] saveSession failed:', e?.message || e)
      })
      return res.user
    } finally {
      loading.value = false
    }
  }

  async function fetchMe() {
    if (!token.value) return null
    try {
      const me = await authApi.me()
      saveUser(me)
      // 同步 IDB 中 user 信息（token 未变）
      saveSession({ token: token.value, user: me }).catch(() => {})
      return me
    } catch {
      clear()
      return null
    }
  }

  async function logout() {
    try {
      await authApi.logout()
    } catch {
      // ignore
    }
    clear()
  }

  function clear() {
    token.value = ''
    saveUser(null)
    tokenStorage.clear()
    // 同步清 IDB（fire-and-forget, 不阻塞路由跳转）
    clearSession().catch((e) => {
      console.warn('[auth] clearSession failed:', e?.message || e)
    })
  }

  async function updateProfile(payload) {
    const u = await authApi.updateProfile(payload)
    saveUser(u)
    // 同步 IDB
    if (token.value) saveSession({ token: token.value, user: u }).catch(() => {})
    return u
  }

  async function changePassword(oldPassword, newPassword) {
    return await authApi.changePassword(oldPassword, newPassword)
  }

  return {
    token,
    user,
    loading,
    ready,
    isAuthenticated,
    isAdmin,
    isTrader,
    isViewer,
    // RBAC
    userRoles,
    roleNames,
    pageKeys,
    hasPageKey,
    hydrate,
    ensureReady,
    login,
    logout,
    clear,
    fetchMe,
    updateProfile,
    changePassword
  }
})
