# Tasks: 2026-07-13-stock-code-picker

## 1. 组件新增（Commit 1 `cce2bd9`）

- [x] 新增 `client/src/components/StockCodePicker.vue`
- [x] 视觉: 左 50% el-autocomplete + 右 50% el-tag
- [x] 复用 `useStocksStore.cache` (v25 落地 5529)
- [x] 复用 v27 `searchCache` 评分算法
- [x] 实现 v-model 严格语义 (契约 1/2/3)
- [x] 文件头注释写明 Props / Emits / 使用场景
- [x] 4 空格缩进 / 行宽 ≤120 / PascalCase 文件名

## 2. OrderForm 试水切换（Commit 2 `d7a9ce1`）

- [x] import 改 `StockCodePicker`
- [x] 组件标签改 `StockCodePicker`
- [x] v-model / `@select` 接口兼容 (Trade.vue 父链不破)
- [x] `@blur` handler 新增, 同步清 `form.stock_name`
- [x] 其它未触及(OrderForm 委托价/委托数量/金额预估/Tab 等)

## 3. OpenSpec 文档（Commit 3）

- [x] `proposal.md` — 背景/目标/不在范围/风险/commit 拆分
- [x] `spec-deltas/frontend.md` — REQ-FE-012 严格语义契约
- [x] `tasks.md` — 本文件
- [ ] 后续 PR 独立合并到 `openspec/specs/frontend/spec.md`（单独 spec sync, 不随本次 commit）

## 4. 验证（已落地 + 待 exec 验证）

- [ ] `npm run build` 通过（待用户在 Trade.vue 切路径实测时跑）
- [ ] Trade.vue (OrderForm) 进入页面实测:
  - [ ] 输入"6005" → blur → form.stock_code 应被清空
  - [ ] 输入"600519" + 点候选 → v-model 应为 "600519.SH"
  - [ ] 重置 form 后 v-model 应同步清空
- [ ] 其它 3 个旧调用方不动, 验证未受波及

## 5. 后续迁移（非本次范围, 独立 PR）

- [ ] T0TaskCreateDialog.vue 切换到 StockCodePicker
- [ ] StrategyConfig.vue 切换
- [ ] AdminStockConfig.vue 切换
- [ ] 决定是否保留 StockCodeAutocomplete.vue
