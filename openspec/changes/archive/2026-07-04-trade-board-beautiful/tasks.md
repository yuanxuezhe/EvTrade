# Tasks — trade-board-beautiful

按依赖顺序, 1 commit。

## 1. OrderForm 三段全宽垂直堆叠 (commit: refactor(client))

- [x] 1.1 改 `client/src/components/OrderForm.vue` 模板:
  - 删 `<div class="price-row">` 整块包裹 (含两个子 `<el-form-item>`)
  - `价格类型` 段升级为独立 `<el-form-item label="价格类型" class="row-tight">`, `el-segmented` 不变
  - `委托价格` 段升级为独立 `<el-form-item label="委托价格" class="row-tight">`, `el-input-number` 不变 (含 `style="width: 100%"`)
  - 段顺序保持: `股票代码` → `价格类型` → `委托价格` → `委托数量`
- [x] 1.2 删 `OrderForm.vue` 中 `.scoped style` 块里的:
  - 整个 `.price-row { ... }` 规则 (含 `display: grid; grid-template-columns: auto 1fr; gap; align-items`)
  - 整个 `.price-type-col { min-width: 180px }` 规则
  - 整个 `.price-col { ... }` 规则 (未引用, 顺带清理)
- [x] 1.3 验证:
  - `cd client && npm test -- --run` → 103 单测全过
  - `cd client && npx vite build` → 构建通过
  - grep 验证: `OrderForm.vue` 中 `.price-row` / `.price-type-col` / `.price-col` 残留 0 处
- [-] 1.4 手动 UI smoke (dev 起后浏览器走一遍) — **deferred by-design, user accepted via /opsx:archive 2026-07-04**:
  - `/trade` 页打开 → `价格类型` 段单独占整行, 4 个 segmented label (`限价` / `最新价` / `挂单价` / `市价`) 完整可见无截断
  - `委托价格` 段独立一行 (限价时 el-input-number 可输入, 市价时 disabled, 占位 "市价单无需输入")
  - `委托数量` 段仍在最下, 含快捷按钮 (`100/500/1千/5千/1万`) 不变
  - 切限价 → 输入价 → 输入量 → 提交按钮依旧走 `ElMessageBox.confirm` 流程

## 2. 价格类型改用 el-radio-group 2×2 grid (commit: refactor(client))

> **r2 修订**: 探索阶段先选 A (`:deep` min-width CSS), 用户实测后改选 C (2×2 grid). 本章节已重新定义为 C.

- [x] 2.1 改 `OrderForm.vue` 模板 + 样式:
  - 模板: 删 `<el-segmented v-model="form.price_type" :options="priceTypeOptions" block size="small" />`
  - 模板: 替换为 `<el-radio-group v-model="form.price_type" class="price-type-grid">` + `<el-radio v-for="opt in priceTypeOptions" :key="opt.value" :value="opt.value" border size="default">{{ opt.label }}</el-radio>`
  - 样式: 删 `:deep(.el-segmented__item) { min-width: 60px }` (随 segmented 一起移除, 不再需要)
  - 样式: 新增 `.price-type-grid { display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-2); width: 100%; }`
  - 样式: 新增 `:deep(.price-type-grid .el-radio) { margin-right: 0; width: 100%; }` 与 `:deep(.price-type-grid .el-radio__wrapper) { display: flex; width: 100%; box-sizing: border-box; justify-content: center; padding-left: var(--space-2); padding-right: var(--space-2); }` 让 border radio 撑满 grid cell
- [x] 2.2 验证:
  - `cd client && npm test -- --run` → 103 单测全过
  - `cd client && npx vite build` → 构建通过
  - grep 验证: `OrderForm.vue` 中无 `el-segmented` 残留; 含 `price-type-grid` `el-radio-group` `el-radio`
- [-] 2.3 手动 UI smoke (覆盖 1.4 同时) — **deferred by-design, user accepted via /opsx:archive 2026-07-04**:
  - `/trade` 页 viewport ≥ 1100px → `价格类型` 段渲染为 2×2 radio grid: 左上 `限价` / 右上 `最新价` / 左下 `挂单价` / 右下 `市价`, 每个 label 完整可见
  - 单击任一 radio → 该 radio 选中 (有圆点 + 边框高亮), `form.price_type` 更新
  - 切市价 (`44`) radio → 委托价格 el-input-number placeholder 变 "市价单无需输入" 且 disabled
  - 切限价 (`11`) radio → 委托价格 el-input-number 恢复可输入, placeholder "输入价格"
