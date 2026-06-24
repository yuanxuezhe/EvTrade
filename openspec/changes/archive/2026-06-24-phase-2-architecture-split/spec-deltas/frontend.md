# REQ-FE-009.7 / 050 / 051: frontend phase-2 拆分

## ADDED Requirements

### REQ-FE-009.7: holdings store 拆分（phase-2 facade）

- **位置**：见 `frontend/spec.md` REQ-FE-009.7 详细说明
- 5 文件: `holdings.js` facade + `holdings_{log,helpers,market,push}.js` 4 个纯工厂

### REQ-FE-050: T0Trade.vue 拆 composables

- **位置**：
  - `client/src/views/T0Trade.vue` — 主壳（1704 行,本次仅拆 2 composables 抽离约 220 行,留 8 子组件后续 phase）
  - `client/src/composables/useT0ChartGeometry.js` — SVG 累计盈亏曲线几何计算（drawer + main 两版）
  - `client/src/composables/useT0OrderSubmit.js` — 下单提交（含价格类型映射/错误码分支）
- **未拆分部分**（deferred to phase-3）：8 个子组件（表单/持仓/委托/统计/drawer 等）仍 inline 在主壳
- 详见归档 `archive/2026-06-24-phase-2-architecture-split/`

### REQ-FE-051: Users.vue 拆 dialogs + useUserActions

- **位置**：
  - `client/src/views/Users.vue` — 主壳（719→250）
  - `client/src/components/users/UserEditDialog.vue` — 编辑 dialog
  - `client/src/components/users/UserResetPwdDialog.vue` — 重置密码 dialog
  - `client/src/composables/useUserActions.js` — 5 步流程 composable（列表/编辑/保存/重置/改密）
- 详见归档 `archive/2026-06-24-phase-2-architecture-split/`

#### Scenario

Given 21 views import `useHoldingsStore()` with various state fields
When `holdings.js` 拆为 facade + 4 helper modules
Then 21 view import 路径不变；`holdingsStore.{positions,orders,trades,cachedAsset,...}` 全部仍可访问
