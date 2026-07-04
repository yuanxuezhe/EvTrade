## ADDED Requirements

### Requirement: OrderForm 三段全宽垂直堆叠（价格类型 / 委托价格 / 委托数量）

The system SHALL 让 `client/src/components/OrderForm.vue` 中
`价格类型` / `委托价格` / `委托数量` 三段各自渲染为独立的 `<el-form-item>`,
每段占满 `<el-form>` 100% 宽度（不再任何 grid 容器共享横向空间）,
确保 `el-segmented` 4 段 (限价 / 最新价 / 挂单价 / 市价) label 在 Trade.vue 左列窄宽度下全部完整可见。

- 字段顺序 MUST 保持: `股票代码` → `价格类型` → `委托价格` → `委托数量`
- 每段 MUST NOT 用 `<div class="price-row">` 等 grid 容器包裹
- `.price-row` / `.price-type-col { min-width: 180px }` / `.price-col` CSS MUST 全部删除

#### Scenario: 价格类型 2×2 radio 网格渲染（r2: 替换 el-segmented）

- **WHEN** user 打开 `/trade` 看到 `OrderForm.vue`
- **THEN** `价格类型` 段 MUST 渲染为独立全宽 `<el-form-item>`, 内含 `<el-radio-group class="price-type-grid">`
- **AND** MUST 渲染 2 行 × 2 列布局: `[限价 | 最新价]` 在上, `[挂单价 | 市价]` 在下
- **AND** 4 个 `<el-radio>` MUST 各占 grid cell 50% 宽度 (CSS `grid-template-columns: 1fr 1fr`)
- **AND** 每个 radio label (`限价` / `最新价` / `挂单价` / `市价`) MUST 完整可见（无 ellipsis 截断）
- **AND** `el-segmented` MUST NOT 在该 view 中出现 (DOM 不含 `.el-segmented` 节点)

#### Scenario: 委托价格独立全宽行渲染

- **WHEN** user 打开 `/trade` 看到 `OrderForm.vue`
- **THEN** `委托价格` 段 MUST 渲染为独立全宽 `<el-form-item>`
- **AND** MUST 与 `价格类型` 段垂直对齐（不共享 grid 行）
- **AND** MUST NOT 含 `.price-row` / `.price-col` 包裹 DOM

#### Scenario: 委托数量保持独立全宽行

- **WHEN** user 打开 `/trade` 看到 `OrderForm.vue`
- **THEN** `委托数量` 段 MUST 仍为独立全宽 `<el-form-item>` (与 `委托价格` 对称, 中间无 grid 容器)

#### Scenario: DOM 不含旧价格行容器

- **WHEN** 浏览器渲染 `OrderForm.vue`
- **THEN** 渲染出的 DOM 中 MUST NOT 出现 `.price-row` 节点
- **AND** MUST NOT 出现 `.price-type-col` / `.price-col` class 包裹元素

#### Scenario: 行为不变

- **WHEN** user 切换 `价格类型` (`限价` / `最新价` / `挂单价` / `市价`) 或输入 `委托价格` / `委托数量`
- **THEN** `form.price_type` / `form.price` / `form.volume` 响应式行为 MUST 与改造前完全一致
- **AND** `handleSubmit` 校验 / `ElMessageBox.confirm` / `props.onSubmit` 调用 MUST 不变
- **AND** radio-group `v-model` 单选互斥 MUST 生效 (任一时刻仅 1 项 checked)
