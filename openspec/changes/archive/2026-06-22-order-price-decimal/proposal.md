# order-price-decimal — 委托价格输入支持小数（限价单）

> MIN 级 / S 工作量。修复用户报障：下单页面限价单价格只能输整数。

## 1. Why

用户报障：下单页限价单价格只接受整数，无法输入小数（如 11.55）。

### 根因

`client/src/components/OrderForm.vue:52`：
```vue
:precision="form.price_type === PriceType.LIMIT ? null : 2"
```

element-plus `el-input-number` 的 `precision` 接受 `number | null`：
- `null` → 显式无精度限制（**实际上无效**，会被组件默认值 0 覆盖）
- 数字 → 保留几位小数

`precision=0` 导致无论 `step=0.01` 多小，输入 11.55 都会四舍五入为 12。

## 2. What Changes

### 2.1 `client/src/components/OrderForm.vue:52` 改 `null → 2`

```vue
:precision="form.price_type === PriceType.LIMIT ? 2 : 2"
```

- 限价单：2 位小数（A 股价格规则，0.01 元最小变动单位）
- 非限价单（市价/最新价/挂单价）：仍是 disabled，precision 无实际作用

**保留** `:step="0.01"`，允许按 0.01 步进加减。

## 3. Capabilities

### Modified Capabilities
- `frontend`: REQ-FE-010 委托价格输入（限价单支持 2 位小数）

## 4. 影响面

- 前端：OrderForm.vue 1 行属性
- 后端：无（后端 `OrderOut.price: float` 本就支持小数）
- 测试：手动验证

## 5. 不在本 change 范围

- 改 ETF/基金价格（3 位小数）——A 股 2 位已满足当前业务
- 改 step 大小为 0.001 —— 越界
- 改 el-input-number 行为 —— 升级 element-plus 可能自然解决

## 6. Tasks

- [ ] T1: `client/src/components/OrderForm.vue:52` 改 `precision="2"`
- [ ] T2: 手动验证：输入 11.55 不再被四舍五入为 12
- [ ] T3: 更新 `openspec/specs/frontend/spec.md` REQ-FE-009
- [ ] T4: commit
