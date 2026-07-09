# Spec Delta: frontend

## ADDED Requirements

### REQ-FE-510: OrderForm 价格类型单行布局 (v15)

The system SHALL render OrderForm.vue 的价格类型选择器为单行 inline radio-button,与 T0Trade 页面的「价格档」视觉风格一致。

#### Scenario: 桌面端 4 个选项排在一行

- **GIVEN** 用户在 Trade.vue 打开 OrderForm,视口宽度 ≥ 1024px
- **WHEN** 渲染价格类型选择器
- **THEN** 4 个选项(限价 / 最新价 / 挂单价 / 市价)以 `el-radio-button` 单行排布
- **AND** 选中态、悬停态沿用 Element Plus 默认 button 样式,无需自定义 grid

#### Scenario: 窄屏自动换行降级

- **GIVEN** 用户在窄屏(视口 < 720px)打开 OrderForm
- **WHEN** 4 个 default-size 按钮宽度超过容器
- **THEN** 沿用 `el-radio-group` 默认 `flex-wrap: wrap`,自动换行(可能 2 行)
- **AND** 不影响选中/提交逻辑

#### Scenario: 数据绑定不变

- **GIVEN** v-model="form.price_type"
- **WHEN** 用户切换价格类型
- **THEN** 委托价格 input 的 disabled / placeholder / `PriceType.LIMIT` 校验逻辑保持原行为
- **AND** 后端 API 调用不变(`{price_type: 11|5|14|44}`)

## REMOVED Requirements

### REQ-FE-OLD-509: OrderForm 价格类型 2×2 grid 布局 (v14, 已废弃)

> 原 v14 trade-board-beautiful r2 设计,使用 `.price-type-grid` + `el-radio` (border) 实现 2×2 网格。v15 重构后被替换为单行 `el-radio-button`,CSS 与 template 同步移除。