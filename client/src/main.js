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

app.use(createPinia())

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
