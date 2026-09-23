import { createApp } from 'vue'
import { createPinia } from 'pinia'

// rbac-roles-module 2026-09-23: 强制清旧 SW + cache (前端 build 时代注册的 SW
//   缓存了旧 chunk-CN2NG2UE.js 引用, 必须 unregister 才不会拿到旧 HTML)
//   仅 dev/preview 启用, 生产用版本化文件名 + content-hash 应不需要 SW
if (typeof navigator !== 'undefined' && 'serviceWorker' in navigator) {
  navigator.serviceWorker.getRegistrations().then((regs) => {
    for (const r of regs) r.unregister()
  })
}

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

const app = createApp(App)

// 注册所有 Element Plus 图标
for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

// 全局指令: v-t0-badge="stock_code" — 在元素内追加绿色 T0 胶囊 (如支持 T+0)
import { t0BadgeDirective } from './directives/t0Badge'
app.directive('t0-badge', t0BadgeDirective)

const pinia = createPinia()
app.use(pinia)

app.use(router)
app.use(ElementPlus, { locale: zhCn })
app.mount('#app')

// 初始化主题：从 localStorage 读取
const savedTheme = localStorage.getItem('evtrade-theme')
if (savedTheme === 'dark') {
  document.documentElement.classList.add('dark')
}
