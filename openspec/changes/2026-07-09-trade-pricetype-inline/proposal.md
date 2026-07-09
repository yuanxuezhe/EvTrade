# Trade 价格类型选择器: 2×2 grid → 单行 radio-button

## Why

交易下单页(Trade.vue / OrderForm.vue)的价格类型选择器当前是 **2×2 grid** 布局,占用一整行 + 4 个 grid cell,视觉上比快速做T页(T0Trade.vue)的**单行 inline radio-button** 笨重,与项目其它快速操作面板(仓位档/历史天数档)不一致。

用户反馈:让 Trade 页价格档与 T0 页风格一致——4 个选项排在一排,选项内容不变(限价/最新价/挂单价/市价)。

## What Changes

**仅改 `client/src/components/OrderForm.vue` 渲染层**,数据流 0 改动。

| 文件 | 行号(旧) | 改动 |
|---|---|---|
| `client/src/components/OrderForm.vue` | 38-51 | `el-radio-group + el-radio(border) + class="price-type-grid"` → `el-radio-group + el-radio-button(size="default")`,结构与 T0Trade 第 18-25 行一致 |
| `client/src/components/OrderForm.vue` | 364-386 | 删除 `.price-type-grid` 及其 `:deep(.price-type-grid .el-radio*)` 死代码 |

**不动**:
- `v-model="form.price_type"` 数据绑定(行号不变)
- `PriceType.LIMIT` 判断逻辑(行 59-61 价格 input disabled、92-93 预估金额、157-165 切换 watch、185-195 提交校验)
- `client/src/constants/priceType.js`(priceTypeOptions 已是 4 项)
- 后端 / stores / router / 其它文件

## Impact

- **能力**: `frontend`(spec delta 在 `spec-deltas/frontend.md`)
- **影响范围**: 仅 Trade.vue 嵌入的 OrderForm;OrderForm 是 Trade.vue 私有使用(grep 验证:仅 Trade.vue 引用)
- **API**: 无变化
- **DB**: 无变化
- **风险**: 低。渲染方式变更,数据流零修改;若 4 个 default-size 按钮在窄屏溢出,因 `el-radio-group` 默认 `flex-wrap: wrap`,会自动换行(降级到 2 行),功能不退化
- **可回滚**: 单文件改动,`git revert <commit>` 即可

## Tasks

- [x] 1. 改 OrderForm.vue 第 38-51 行 template
- [x] 2. 删 OrderForm.vue 第 364-386 行 CSS 死代码
- [x] 3. `git diff --stat` 校验 ≤ 20 行
- [x] 4. commit `feat(orderform): 价格类型改为单行 radio-button 与 T0 一致`
- [x] 5. `openspec sync` 合 frontend spec
- [x] 6. `openspec archive` 入 archive/

## 关联

- `client/src/views/T0Trade.vue` 第 18-25 行(参考实现)
- `client/src/constants/priceType.js`(共享常量)