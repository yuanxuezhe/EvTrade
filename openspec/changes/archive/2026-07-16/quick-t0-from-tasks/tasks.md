# tasks.md — 2026-07-16-quick-t0-from-tasks

> 实施 checklist，按 4 commit 顺序排列。每个子任务粒度 2–5 分钟。

## Commit 1 — T0TaskCreateDialog 接 external stockCode

> 范围：`client/src/components/trade/T0TaskCreateDialog.vue`（单文件）

### 子任务

- [ ] 1.1 读现状 `T0TaskCreateDialog.vue` 全文（166 行）
- [ ] 1.2 新增 `externalStockCode: { type: String, default: '' }` prop
- [ ] 1.3 新增 `update:externalStockCode` emit（v-model 用）
- [ ] 1.4 watch externalStockCode → 若与 form.stock_code 不同，自动写入 form（同时清校验）
- [ ] 1.5 StockCodePicker 改用 `v-model` 与 external 联动
- [ ] 1.6 vue-tsc --noEmit 验证 0 错

**commit msg**：
```
feat(dialog): T0TaskCreateDialog 接 external stockCode prop 让 HoldingsPanel 选中能驱动表单
```

**影响**：1 文件 +20 行 / -5 行
**verify**：vue-tsc 0 + 单文件回归

## Commit 2 — HoldingsPanel 加 select-stock emit

> 范围：`client/src/components/trade/HoldingsPanel.vue`（单文件，最小改动）

### 子任务

- [ ] 2.1 现状有 dblclick → emit `apply-to-order`，**保留不动**
- [ ] 2.2 新增 emit `select-stock`（单击触发）
- [ ] 2.3 row 添加 `@row-click="onRowClick"`（v-on 默认 click）
- [ ] 2.4 onRowClick → emit `select-stock({ stock_code, stock_name, vol, avl_vol })`
- [ ] 2.5 不要触发 dblclick（用 flag 控制，与 apply-to-order 不冲突）
- [ ] 2.6 vue-tsc 验证

**commit msg**：
```
feat(panel): HoldingsPanel 加 select-stock emit (单击) — 不改 dblclick apply-to-order 语义
```

**影响**：1 文件 +15 行 / -0 行
**verify**：vue-tsc 0 + 单文件回归（Trade.vue 不受影响）

## Commit 3 — T0Trade.vue 主表切到 task 视角 + dialog 集成

> 范围：`client/src/views/T0Trade.vue`（主改动）

### 子任务

- [ ] 3.1 读现状 T0Trade.vue 全文 666 行
- [ ] 3.2 header L47 改 "管理任务" → "添加任务"（type=primary，icon `+`，点击 → createDialogVisible=true）
- [ ] 3.3 删 L176-191 T0TaskList drawer 段
- [ ] 3.4 T0TaskCreateDialog 段改宽到 900px + 加 HoldingsPanel 同行（grid 2 列）
- [ ] 3.5 HoldingsPanel @select-stock 监听 → 写入 createForm.stock_code
- [ ] 3.6 **主表数据源** `holdingsPositions` → `t0TasksStore.tasks`（computed）
- [ ] 3.7 **主表列重设 8 列**：状态/任务编号/标的代码/名称/底仓+目标/当前持仓/做T盈亏/做T收益率/操作
- [ ] 3.8 task 操作按钮：配平（store.balanceTask）/ 平仓（store.closeTask）/ 详情（路由 /t0-tasks/:id 或 drawer 弹 T0TaskDetail）
- [ ] 3.9 empty-text 改"暂无 T0 任务，点击「添加任务」按钮创建"
- [ ] 3.10 删除 unused imports（holdings columns / old drawer refs）
- [ ] 3.11 vue-tsc 验证 0 错

**commit msg**：
```
feat(ui): T0Trade 主表切到 task 视角 — 8 列任务列表; header 改"添加任务"按钮 + dialog 内嵌 HoldingsPanel 让用户点持仓行自动填 stock_code 创建任务
```

**影响**：1 文件 大改 -200 / +180 行（净减 ~20 行）
**verify**：vue-tsc 0 + 浏览器实测添加任务全流程

## Commit 4 — spec + archive + push

> 范围：`openspec/specs/frontend/spec.md` + `openspec/changes/archive/`

### 子任务

- [ ] 4.1 写 `spec-deltas/frontend.md`（REQ-FE-230）
- [ ] 4.2 append REQ-FE-230 到主 spec
- [ ] 4.3 mv changeset 到 archive/2026-07-16/quick-t0-from-tasks
- [ ] 4.4 git commit + push
- [ ] 4.5 远端 HEAD 确认 = local HEAD

**commit msg**：
```
docs(spec): REQ-FE-230 T0Trade 主表切到 task 视角 + 添加任务 dialog 嵌入 HoldingsPanel
```

## Verify 全程

- vitest 62/62 PASS（v54 lib 不动 → 无影响）
- vue-tsc --noEmit 0 错
- 浏览器实测：登录 → /quick-t0 → 主表 8 列精准 → 点"添加任务" → dialog → 左侧 HoldingsPanel 可见持仓 → 点持仓行 → 表单 stock_code 自动回填 → 创建 → 主表新增一行 task
- DOM 实测：主表 1 行 = 1 task 8 列字段
- 视觉：vision 截图二次复检（用户硬性偏好 #7）