# tasks — bundle-shrink-round-3

## P0 — 摸清单 + 安全确认

- [x] grep `from 'element-plus'` 命中 27 文件, 按 1 文件 1 行列出 (按 mass-rollout skill §3 P2)
- [x] 确认所有用到的 API (ElMessage / ElMessageBox / ElNotification 三个) 都在 `element-plus/es` 命名导出里
- [x] 不存在稀有用 `ElLoading` `.service()` / `ElMessage({dangerouslyUseHTMLString})` 等需要单独子路径的代码

## P1 — 1 文件 1 patch (按字母 / 目录顺序)

按 vue-component-mass-rollout skill §3 P3-P4 严格顺序:

### components/
- [x] CacheTableView.vue (ElMessage, ElMessageBox)
- [x] ChangePasswordDialog.vue (ElMessage)
- [x] OrderForm.vue (ElMessage, ElMessageBox)
- [x] strategy/BacktestForm.vue (ElMessage)
- [x] strategy-order/StrategyOrderCreatePanel.vue (ElMessage)
- [x] strategy-order/StrategyOrderList.vue (ElMessage, ElMessageBox)
- [x] trade/TodayOrdersPanel.vue (ElMessage, ElMessageBox)

### composables/
- [x] useT0OrderSubmit.js (ElMessage)
- [x] useUserActions.js (ElMessage, ElMessageBox)

### stores/
- [x] order.js (ElMessageBox)
- [x] ws_dispatch.js (ElNotification)

### views/
- [x] AdminStockConfig.vue (ElMessage)
- [x] CachePositions.vue (ElMessage)
- [x] HistoryQuoteCompletion.vue (ElMessage, ElMessageBox)
- [x] Position.vue (ElMessage)
- [x] Profile.vue (ElMessage)
- [x] Roles.vue (ElMessage, ElMessageBox)
- [x] ScriptDev.vue (ElMessage, ElMessageBox)
- [x] ScriptTask.vue (ElMessage, ElMessageBox)
- [x] StkPoolView.vue (ElMessage)
- [x] StkPool.vue (ElMessage, ElMessageBox)
- [x] StrategyOrder.vue (ElMessage)
- [x] SystemConfig.vue (ElMessage, ElMessageBox)
- [x] SystemInit.vue (ElMessage, ElMessageBox)
- [x] T0Trade.vue (ElMessage, ElMessageBox)
- [x] Trade.vue (ElMessage)
- [x] Users.vue (ElMessage)

## P2 — 验证

- [x] `grep -rE "from 'element-plus'(?!.*es)" client/src/` → 0 命中
- [x] `cd client && npm run build` 通过
- [x] vite dev 浏览器手测关键路径 (登录 / Dashboard / Trade / T0)

## P3 — KB + spec merge + commit

- [x] `知识库/前端/架构概览.md` 追加 REQ-FE-553 段
- [x] `openspec/specs/frontend/spec.md` 追加 REQ-FE-553 段
- [x] 归档 change → archive/
- [x] commit "feat(frontend): 27 业务文件 ElMessage 等改 element-plus/es 子路径 (REQ-FE-553)"
