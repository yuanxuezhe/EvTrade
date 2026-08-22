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
    hydrate,
    login,
    logout,
    clear,
    fetchMe,
    updateProfile,
    changePassword
  }
})
