# Spec Delta: frontend — StockCodePicker 严格语义契约（v28）

**Change**: 2026-07-13-stock-code-picker
**Target**: `openspec/specs/frontend/spec.md`（追加 REQ-FE-012）

## 增量内容

### 新增 REQ-FE-012: StockCodePicker.vue 严格语义契约（v28）

**Given** v27 `StockCodeAutocomplete` 在"打字未选中"的中间态时仍 emit 半选代码
（例：输入 `"6005"` 就 emit `"6005"`），导致下游（OrderForm.handleSubmit / QuotePanel 行情订阅）
拿到**未经验证**的代码

**When** 设计 `StockCodePicker.vue` 作为 v28 强化版

**Then** MUST 满足：

- 组件位置：`client/src/components/StockCodePicker.vue`
- 视觉布局：**左 50% 宽度** `el-autocomplete` 输入框 + **右 50% 宽度** `el-tag`
  （只读不可关闭）显示已选证券名称；未选中时右侧显示"请选择股票"占位
- 数据源：复用 `useStocksStore.cache`（v25 落地 5529 行）+ 复用 v27 `searchCache`
  评分算法（code 前缀(3) > short_name 前缀(2) > name 包含(1)）
- Props:
  - `modelValue: string` — v-model 纯 stock_code
  - `placeholder: string` — 默认"输入代码 / 名称 / 首字母"
  - `disabled: boolean` — 默认 false
  - `clearable: boolean` — 默认 true
  - `triggerOnFocus: boolean` — 默认 false
  - `size: 'default' | 'small' | 'large'` — 透传
  - **`tagType: 'primary' | 'success' | 'info' | 'warning' | 'danger'`** — el-tag 类型, 默认 primary
- Emits:
  - `update:modelValue (string)` — **只emit真正选中值或blur清空信号**, 不在打字中间态emit半选code
  - `select (stock)` — 候选被选中时发完整 stock 对象
  - `blur ()` — 失焦
- **契约 1: v-model 严格性**
  - 只有 `onSelectItem` 真正从候选中选择时, 才 emit `update:modelValue(<real_code>)`
  - 用户中途打字（未点候选）→ 输入框可以打字, 但**不emit update:modelValue**
  - 用户**已选之后再打字改输入框**内容 → 输入框可以打字, 但同样**不立即emit**
    （等下次blur 才决定清空还是重新选中）
- **契约 2: blur 清空**
  - `onBlur()` 检查: 若 `inputText !== selectedStock.code`,
    则 emit `update:modelValue('')` + 清空 `selectedStock`
  - 这样保证**未确定的中间态绝不污染 v-model**
- **契约 3: 父组件 v-model 双向同步**
  - 父组件 reset / defaultStockCode 预填 → 内部 `watch(props.modelValue)` 同步
  - 父组件把 v-model 置空 → 内部 `inputText` + `selectedStock` 同步清
- 错误降级：`loadCache()` 失败时 input 仍可手动输入, 候选列表为空

#### Scenario: 输入"600519.SH" → 选中候选 → blur 不动

- **GIVEN** `useStocksStore.cache` 已 loaded, cache 含 `600519.SH`
- **WHEN** StockCodePicker 输入框输入 `600519`
- **THEN** 候选"600519.SH 贵州茅台 [GZMT]" 弹出（score=3）
- **WHEN** 点击候选
- **THEN** emit `update:modelValue('600519.SH')` + emit `select({stock_code:'600519.SH', stock_name:'贵州茅台', ...})`
- **WHEN** blur
- **THEN** inputText===selectedStock.code, 无 emit(''), 控件保留已选

#### Scenario: 输入"6005" → 未选 → blur 自动清空

- **GIVEN** 控件当前未选中任何股票
- **WHEN** 输入框输入 `6005`（未点候选）
- **THEN** 候选列表弹出, 但 v-model 未发生变化（emit 不被触发）
- **WHEN** 用户移开焦点（blur）
- **THEN** blur 处理逻辑判断: inputText='6005' !== selectedStock=null, **emit `update:modelValue('')`**,
  清空 internal state
- **AND** 父组件 form.stock_code 收到 '', 下游下单按钮 disabled / 下单校验拦截

#### Scenario: 已选"600519.SH"后改输"000001.SZ"

- **GIVEN** 控件已选中 `600519.SH`
- **WHEN** 用户在输入框清空重新输入 `000001.SZ`（未点候选）
- **THEN** v-model 仍保持 `600519.SH`（emit 未触发）, 输入框显示`000001.SZ`,
  el-tag 仍显示"贵州茅台"
- **WHEN** blur
- **THEN** inputText='000001.SZ' !== selectedStock.code='600519.SH',
  emit `update:modelValue('')`, 内部全清
- **AND** 用户可重新选股（既可重新输入也可再次点候选）

#### Scenario: 父组件 reset 同步

- **GIVEN** 控件已选中 `600519.SH`
- **WHEN** 父组件 form.stock_code 被重置为 ''
- **THEN** 内部 watch(props.modelValue) 触发, `inputText=''` + `selectedStock=null`,
  右侧 el-tag 隐藏, 显示"请选择股票"占位

### 与 REQ-FE-011 (StockCodeAutocomplete) 关系

- **保留 `StockCodeAutocomplete.vue`**: 不删, 不破; 4 个现有调用方保持
  (`T0TaskCreateDialog` / `StrategyConfig` / `AdminStockConfig` / 旧的 `OrderForm` snapshot)
- **迁移路径**: 由独立 PR / change 推进, 本次仅 `OrderForm.vue` 首批试水
- **取舍**: StockCodePicker 是 v28 新增组件, v27 文档契约仍有效; 两者并存
