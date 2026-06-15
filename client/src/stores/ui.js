import { defineStore } from 'pinia'
import { ref, watch, onMounted, onBeforeUnmount } from 'vue'

export const useUiStore = defineStore('ui', () => {
  const sidebarCollapsed = ref(localStorage.getItem('evtrade-sidebar') === '1')

  // 移动端断点
  const MOBILE_BP = 900
  const isMobile = ref(false)

  // 移动端侧栏抽屉
  const mobileSidebarOpen = ref(false)

  // 主题
  const theme = ref(localStorage.getItem('evtrade-theme') || 'light')

  function toggleTheme() {
    theme.value = theme.value === 'dark' ? 'light' : 'dark'
    localStorage.setItem('evtrade-theme', theme.value)
    document.documentElement.classList.toggle('dark', theme.value === 'dark')
  }

  // 初始化时应用主题
  if (typeof document !== 'undefined') {
    document.documentElement.classList.toggle('dark', theme.value === 'dark')
  }

  function _applyBreakpoint() {
    // 调试覆盖：URL ?mobile=1 强制移动端（不依赖物理视口）
    const forced = new URLSearchParams(window.location.search).get('mobile') === '1'
    const w = window.innerWidth
    const m = forced || w <= MOBILE_BP
    const was = isMobile.value
    isMobile.value = m
    // 切回桌面时自动关闭抽屉
    if (was && !m) mobileSidebarOpen.value = false
  }

  // 监听（SSR-safe）
  if (typeof window !== 'undefined') {
    _applyBreakpoint()
    window.addEventListener('resize', _applyBreakpoint)
  }

  function toggleSidebar() {
    if (isMobile.value) {
      mobileSidebarOpen.value = !mobileSidebarOpen.value
    } else {
      sidebarCollapsed.value = !sidebarCollapsed.value
      localStorage.setItem('evtrade-sidebar', sidebarCollapsed.value ? '1' : '0')
    }
  }

  // 路由切换时关闭抽屉
  function onRouteChange() {
    if (mobileSidebarOpen.value) mobileSidebarOpen.value = false
  }

  return {
    sidebarCollapsed,
    isMobile,
    mobileSidebarOpen,
    theme,
    toggleSidebar,
    toggleTheme,
    onRouteChange,
  }
})
