## Why

`client/src/components/OrderForm.vue` 左侧下单面板在 `Trade.vue` 左列里渲染时, `价格类型` 与 `委托价格` 共享一行 (`<div class="price-row">` grid `auto 1fr`), 4 段 el-segmented 选项 (`限价` / `最新价` / `挂单价` / `市价`) 在窄列下被横向挤压, 选项文本显示不全。`委托数量` 因已经在独立一行(`<el-form-item>` full row)不受影响, 用户希望把 `委托价格` 也独立成单独一行, 按 `价格类型 → 委托价格 → 委托数量` 三行垂直堆叠, 每个控件占满表单宽度, 释放 segmented 的横向空间。

## What Changes

- 改 `client/src/components/OrderForm.vue`:
  - 移除 `<div class="price-row">` grid 容器 (`.price-row` CSS 一并删除)
  - `价格类型` 段 `<el-form-item class="row-tight price-type-col">` 提升为独立 `<el-form-item>`
  - `委托价格` 段 `<el-form-item class="row-tight price-col">` 也升级为独立 `<el-form-item>`
  - 三段 `el-form-item` 顺序: `股票代码` → `价格类型` → `委托价格` → `委托数量` (其余不变)
- 删 `OrderForm.vue` 中仅服务于 grid 的 CSS 规则:
  - `.price-row` 整个块
  - `.price-type-col { min-width: 180px }` (不再需要)
  - `.price-col` (未使用, 顺便清理)
- **BREAKING**: 无 (layout-only, 行为/数据契约全部不变)

## Capabilities

### New Capabilities
(无)

### Modified Capabilities
- `frontend`: 调整 `OrderForm.vue` 布局 — `价格类型` / `委托价格` / `委托数量` 改为 3 个独立全宽 `<el-form-item>` 垂直堆叠

## Impact

- 受影响文件:
  - `client/src/components/OrderForm.vue` (template + scoped style; 不动 script 逻辑)
- 不影响数据流, 不影响 `OrderType` / `PriceType` 常量, 不影响 `api.placeOrder` 契约, 不影响单测 (无相关 unit test 覆盖布局)
- 验证: `cd client && npm test -- --run` + `npx vite build` 仍绿
