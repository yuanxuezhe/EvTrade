# bundle-shrink-round-3（剩余 view/composable/store 整包改子路径）— 2026-09-23

## 解决什么

`REQ-FE-551` + `REQ-FE-552` 已把 layout / main.js 的 `from 'element-plus'` 整包改 `'element-plus/es'`（3 个文件）。
但项目里**还有 27 个 .vue / .js 文件**仍写 `from 'element-plus'` 整包路径（grep 2026-09-23 全扫）：

```
CacheTableView.vue        ElMessage, ElMessageBox
ChangePasswordDialog.vue  ElMessage
OrderForm.vue             ElMessage, ElMessageBox
strategy/BacktestForm.vue ElMessage
strategy-order/StrategyOrderCreatePanel.vue  ElMessage
strategy-order/StrategyOrderList.vue         ElMessage, ElMessageBox
trade/TodayOrdersPanel.vue                   ElMessage, ElMessageBox
composables/useT0OrderSubmit.js  ElMessage
composables/useUserActions.js    ElMessage, ElMessageBox
stores/order.js                  ElMessageBox
stores/ws_dispatch.js            ElNotification
views/AdminStockConfig.vue       ElMessage
views/CachePositions.vue         ElMessage
views/HistoryQuoteCompletion.vue ElMessage, ElMessageBox
views/Position.vue               ElMessage
views/Profile.vue                ElMessage
views/Roles.vue                  ElMessage, ElMessageBox
views/ScriptDev.vue              ElMessage, ElMessageBox
views/ScriptTask.vue             ElMessage, ElMessageBox
views/StkPoolView.vue            ElMessage
views/StkPool.vue                ElMessage, ElMessageBox
views/StrategyOrder.vue          ElMessage
views/SystemConfig.vue           ElMessage, ElMessageBox
views/SystemInit.vue             ElMessage, ElMessageBox
views/T0Trade.vue                ElMessage, ElMessageBox
views/Trade.vue                  ElMessage
views/Users.vue                  ElMessage
```

这些整包 import 每被首次访问，vite deps prebundle 都会重新生成 88KB `element-plus.js` bundle
(REQS-FE-551/552 已限制只 layout-essential 不触发，但其它 view 一旦路由到仍触发 prebundle)。

按 § P5 阶段拍板，要彻底消除整包 deps bundle 出现，必须把这 27 文件全部改子路径。

## 改动

### 1 文件 1 patch 严格顺序

每个文件:
```js
// 旧
import { ElMessage, ElMessageBox } from 'element-plus'

// 新
import { ElMessage, ElMessageBox } from 'element-plus/es'  // REQ-FE-552.2
```

注释风格复用 FE-552 一致的 `// REQ-FE-552.2: ...` 注释.

### 不改的说明 (拍板存档)

- `views/*.vue` template 里 `<el-*>` 已经在 FE-551 由 unplugin 按需注入. 改完子路径后:
  - 文件头 `/* unplugin-vue-components disabled */` marker 消失 (因为它之前是被 hand-整包 import 触发的)
  - `<el-button>` / `<el-icon><Edit /></el-icon>` 标签重新按 unplugin 自动注入.
- 27 文件全部用 `ElMessage` / `ElMessageBox` / `ElNotification` 三个 API, 都在 `element-plus/es` 命名导出里
  (确认 v2.5+ ESM tree-shake 后内部一致). 不存在稀有 API 需要单独子路径.

## 影响面

- 27 文件 import 路径变更 + 注释
- 后端 0 改动
- store 0 改动 (只改 import 路径, store action 逻辑不变)
- router 0 改动 (路由 lazy 已在 FE-551 拍板)
- API 0 改动

## 验证

1. `grep -rE "from 'element-plus'(?!.*es)" client/src/` → 0 命中
2. vite dev 浏览器手测: 登录 / Dashboard / Trade / T0 / Users / Roles / ScriptDev / ScriptTask 关键路径
3. `cd client && npm run build` 通过
4. vite deps cache 不再生成 `element-plus.js` deps bundle (虽然路径仍存在但内容空 / 文件不存在)
