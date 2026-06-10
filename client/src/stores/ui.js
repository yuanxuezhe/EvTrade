import { defineStore } from 'pinia'
import { ref, watch } from 'vue'

export const useUiStore = defineStore('ui', () => {
  const sidebarCollapsed = ref(localStorage.getItem('evtrade-sidebar') === '1')
  const theme = ref(localStorage.getItem('evtrade-theme') || 'light')
  const lastRefreshAt = ref(null)

  function toggleSidebar() {
    sidebarCollapsed.value = !sidebarCollapsed.value
    localStorage.setItem('evtrade-sidebar', sidebarCollapsed.value ? '1' : '0')
  }

  function toggleTheme() {
    theme.value = theme.value === 'dark' ? 'light' : 'dark'
    applyTheme()
  }

  function applyTheme() {
    if (theme.value === 'dark') {
      document.documentElement.classList.add('dark')
    } else {
      document.documentElement.classList.remove('dark')
    }
    localStorage.setItem('evtrade-theme', theme.value)
  }

  function markRefreshed() {
    lastRefreshAt.value = new Date()
  }

  // 初次同步
  applyTheme()

  watch(theme, applyTheme)

  return {
    sidebarCollapsed,
    theme,
    lastRefreshAt,
    toggleSidebar,
    toggleTheme,
    markRefreshed
  }
})
