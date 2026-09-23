# bundle-shrink-round-2（首屏主图再瘦身：layout 拆包 + ElMessage 子路径）— 2026-09-23

## 解决什么

第一阶段 `element-plus-auto-import` 已把 element-plus 1.2MB → 88KB（13.6×），但用 curl 抓
`http://192.168.10.2:50998/` 实际加载瀑布（实时抓 ~120 个 URL）发现首屏主图仍重：

1. **AppHeader.vue 引 `import { ElMessage, ElMessageBox } from 'element-plus'` 整包路径（61 KB）**
   → vite deps prebundle 整包 → `element-plus.js?v=ea2b7376` 88 KB 重新出现在 chunk list，
   绕开了 REQ-FE-551 按需引入。文件头自动插 `/* unplugin-vue-components disabled */`，
   AppHeader.vue 模板里 `<el-dropdown> <el-button> <el-input>` 等 el-* 不被按需注入。
2. **OperationLog.vue 同款** 30+ KB，整包 import 同样影响。
3. **Layout 4 个组件（Sidebar / AppHeader / OperationLog / BottomNav）都 eager import 到 App.vue**
   → 路由无论去哪个页面都要先 mount 这 4 个 layout 组件；其中 Sidebar 还引 useRoute/useUiStore/useAuthStore,
   AppHeader 引 5 个 store + 多个 el-icon component, 都额外增重。

实测顺序（vite dev 顺序瀑布 from 192.168.10.2:50998）：
```
HTML 2.4 KB → vite-client 134 KB → main.js 10 KB → App.vue → Sidebar+AppHeader+OperationLog+BottomNav (mounted together)
  → ui+auth+ws+holdings+stocks stores (eager) → 5 个 view-private stores (eager via App.vue 引 useHoldingsStore)
  → element-plus_es 按需 deps 88 KB + 8 个 css chunk + @element-plus/icons-vue 70 KB
  → element-plus.js 整包 88 KB (Login/AppHeader/OperationLog 触发)
  → 视图 EChart + StatCard + OrderStatusBadge + cells/StockTargetCell 等
  → 5 个 ws + 4 个 /api/* (业务数据)
```

## 改动

### A — Layout 4 组件改 lazy mounted via `<Suspense>` + `defineAsyncComponent`

App.vue 当前:
```js
import Sidebar from './components/Sidebar.vue'
import AppHeader from './components/AppHeader.vue'
import OperationLog from './components/OperationLog.vue'
import BottomNav from './components/BottomNav.vue'
```

改为（保持视觉一致, 配合 `<Suspense>` 保持同步数据接口）：
```js
import { defineAsyncComponent } from 'vue'
const Sidebar     = defineAsyncComponent(() => import('./components/Sidebar.vue'))
const AppHeader   = defineAsyncComponent(() => import('./components/AppHeader.vue'))
const OperationLog = defineAsyncComponent(() => import('./components/OperationLog.vue'))
const BottomNav   = defineAsyncComponent(() => import('./components/BottomNav.vue'))
```

`v-if` 已有（OperationLog `v-if=authStore.isAuthenticated && !uiStore.isMobile`,
BottomNav `v-if=authStore.isAuthenticated && uiStore.isMobile`），所以即便首屏未登录，
未命中分支，组件 import 时机延后到 v-if=true 才 fetch。

**注**：vue3 `<script setup>` 顶层 await 不被 Suspense 完整识别，但这些 layout 组件的 setup
已经是同步（参照 StockTargetCell pattern），所以 Suspense 不必，defineAsyncComponent 单独用即可。

### B — 整包 `from 'element-plus'` 改子路径 `from 'element-plus/es'`

3 个文件:
- `client/src/views/Login.vue:119` — `import { ElMessage } from 'element-plus'`
- `client/src/components/AppHeader.vue:93` — `import { ElMessage, ElMessageBox } from 'element-plus'`
- `client/src/components/OperationLog.vue:105` — `import { ElMessage, ElMessageBox } from 'element-plus'`

改:
```js
import { ElMessage } from 'element-plus/es'           // Login
import { ElMessage, ElMessageBox } from 'element-plus/es'   // AppHeader / OperationLog
```

理由: `element-plus/es` 是按需的 ESM entry, vite deps prebundle 不会被预构造成 88 KB,
而是直接 bundler 透传 → unplugin 模板扫描的 el-* 按需注入重新生效（disabled marker 消失）,
AppHeader 整文件砍 ~30-50 KB。

## 不做（无法优化的部分，拍板记录）

按 § 4 P3 阶段明示：

- **App.vue 顶层 5 个 stores（ui/auth/ws/holdings/stocks）必须 eager**：启动屏障
  `await authStore.hydrate()` + `holdingsStore.bootstrap()` + `stocksStore.initCache()`
  全在 App.vue setup 同步执行，必须提前 mount。
- **5 个全局 WS 频道 + `/api/asset/holdings/quote/snapshots`** 业务数据是登录后必需，无优化空间。
- **element-plus/dist/index.css 整包 CSS**（gzip 后 ~30 KB）保留，css 按需需要 .scss loader，
  复杂度不值（已在 REQ-FE-551.4 拍板）。
- **`@element-plus/icons-vue` 整个 ESM bundle（70 KB）**：unplugin ElementPlusResolver 仍会
  prebundle 整 icons set, 因为 view 模板用到 26 个不同 <el-icon><PascalName /></el-icon> 静态标签,
  静态分析虽然按需 import 名字, 但 single deps bundle 仍被 vite 缓存一次; 优化需要"按 icon 拆包"
  on-demand per-file import, 引入 unplugin-icons resolver + 散开 import 路径（30 个文件），
  ROI 不划算, 留待后续。

## 影响面

- 仅前端 5 文件改动: 4 个 layout (.vue) + 1 个 App.vue + 3 个 import 子路径化 (Login/AppHeader/OperationLog)
- 路由器 / store / API / 业务 view: 0 改动
- 服务端: 0 改动
- DB: 0 改动

## 验证

1. `curl http://192.168.10.2:50998/src/App.vue` 看返回头是否有 `defineAsyncComponent`
2. `curl http://192.168.10.2:50998/src/views/Login.vue` 看 import path 是否 `element-plus/es`
3. `curl http://192.168.10.2:50998/src/components/AppHeader.vue` / `OperationLog.vue` 同上
4. 业务功能手工验 (login / Dashboard / Trade / T0 / OperationLog 收发)
5. `cd client && npm run build` build 通过
