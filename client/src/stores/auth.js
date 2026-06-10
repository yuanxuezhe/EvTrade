import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { authApi, tokenStorage } from '../api'

const USER_KEY = 'evtrade-user'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(tokenStorage.get() || '')
  const user = ref(loadUser())
  const loading = ref(false)

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

  async function login(username, password) {
    loading.value = true
    try {
      const res = await authApi.login(username, password)
      token.value = res.access_token
      tokenStorage.set(res.access_token)
      saveUser(res.user)
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
  }

  async function updateProfile(payload) {
    const u = await authApi.updateProfile(payload)
    saveUser(u)
    return u
  }

  async function changePassword(oldPassword, newPassword) {
    return await authApi.changePassword(oldPassword, newPassword)
  }

  return {
    token,
    user,
    loading,
    isAuthenticated,
    isAdmin,
    isTrader,
    isViewer,
    login,
    logout,
    clear,
    fetchMe,
    updateProfile,
    changePassword
  }
})
