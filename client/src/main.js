import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/dist/locale/zh-cn.mjs'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import 'element-plus/dist/index.css'
import './assets/styles/main.css'
import App from './App.vue'
import router from './router'
import { rehydrateFromIDB } from './utils/cacheRehydrate'

const app = createApp(App)

// 注册所有 Element Plus 图标
for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

app.use(createPinia())
app.use(router)
app.use(ElementPlus, { locale: zhCn })

// 在 App mount 之前从 IndexedDB 恢复 4 张业务表 (资金/持仓/委托/成交)
// 失败不阻塞启动, 降级为空缓存
rehydrateFromIDB().finally(() => {
  app.mount('#app')
})

// 初始化主题：从 localStorage 读取
const savedTheme = localStorage.getItem('evtrade-theme')
if (savedTheme === 'dark') {
  document.documentElement.classList.add('dark')
}
