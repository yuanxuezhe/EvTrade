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

// REQ-FE-551: element-plus 组件与图标已改为按需引入 (vite.config.js
//   unplugin-vue-components + ElementPlusResolver), 模板里的 <el-button> /
//   <Edit /> 静态标签会在 transform 时被 resolver 自动注入 import + register.
//   element-plus 的 CSS 与整体 locale (zh-cn) 由 ElementPlusResolver 的
//   `locale: 'zh-cn'` + `importStyle: 'css'` 选项自动按 el-* 用到的组件插入
//   对应的 lang/<comp>.mjs 片段 — 因此不再需要 main.js 全量 import ElementPlus
//   或 zhCn, 不再需要全量 Object.entries(ElementPlusIconsVue) 280+ 图标注册循环.
//   el-table 等内置文案 (分页 "共 / 条", 空数据 "暂无数据") 仍走 zh-cn locale.
//   CSS 仍整包 import 'element-plus/dist/index.css' 因为 perf 已不是瓶颈 (gzip 后 ~30KB),
//   且 css 按需需要 .scss loader, 复杂度不值.
import 'element-plus/dist/index.css'
import './assets/styles/main.css'
import './styles/trade-panel.css'
// REQ-LOG-006: 前端日志器初始化 (window.__evtradeDownloadLog / __evtradeSetLogLevel / __evtradeGetLogLevel / __evtradeLogStats / __evtradeClearLog)
import './utils/logger'
import App from './App.vue'
import router from './router'

const app = createApp(App)

// 全局指令: v-t0-badge="stock_code" — 在元素内追加绿色 T0 胶囊 (如支持 T+0)
import { t0BadgeDirective } from './directives/t0Badge'
app.directive('t0-badge', t0BadgeDirective)

const pinia = createPinia()
app.use(pinia)

app.use(router)
app.mount('#app')

// 初始化主题：从 localStorage 读取
const savedTheme = localStorage.getItem('evtrade-theme')
if (savedTheme === 'dark') {
  document.documentElement.classList.add('dark')
}
