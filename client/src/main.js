import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/dist/locale/zh-cn.mjs'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import 'element-plus/dist/index.css'
import './assets/styles/main.css'
import './styles/trade-panel.css'
// REQ-LOG-006: 前端日志器初始化 (window.__evtradeDownloadLog / __evtradeSetLogLevel / __evtradeGetLogLevel / __evtradeLogStats / __evtradeClearLog)
import './utils/logger'
import App from './App.vue'
import router from './router'
import { useAuthStore } from './stores/auth'

const app = createApp(App)

// 注册所有 Element Plus 图标
for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

// 全局指令: v-t0-badge="stock_code" — 在元素内追加绿色 T0 胶囊 (如支持 T+0)
import { t0BadgeDirective } from './directives/t0Badge'
app.directive('t0-badge', t0BadgeDirective)

// 2026-08-21 fix: 显式 setActivePinia, 否则顶层 useAuthStore() 报
//   "getActivePinia() was called but there was no active Pinia"
//   (app.use(pinia) 不会立刻激活 active pinia, 需 setActivePinia)
import { setActivePinia } from 'pinia'
const pinia = createPinia()
setActivePinia(pinia)
app.use(pinia)

// v119: 启动屏障 — 在 router 安装前 await IDB token 恢复
// 避免首轮 beforeEach 读不到 token 误跳 /login (Pinia store 初始化时 localStorage
// 可能还没回填, IDB 加载又异步; 等 hydrate 完成再装路由才能拿到正确 auth 状态)
const auth = useAuthStore()
await auth.hydrate()

app.use(router)
app.use(ElementPlus, { locale: zhCn })
app.mount('#app')

// 初始化主题：从 localStorage 读取
const savedTheme = localStorage.getItem('evtrade-theme')
if (savedTheme === 'dark') {
  document.documentElement.classList.add('dark')
}
