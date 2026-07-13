# Proposal: StockCodePicker.vue — 输入合法性强化

**Change ID**: `2026-07-13-stock-code-picker`
**Date**: 2026-07-13
**Status**: Proposed

## 背景

v25/v26/v27 演进路线：
- **v25** (2026-07-12-stocks-cache-and-short-name): 全量 5529 行股票内存缓存 + AdminStockConfig 用 autocomplete
- **v26** (2026-07-12-universalize-stockcode-autocomplete): 通用化，下单入口三件套接入
- **v27** (2026-07-12-universalize-stockcode-autocomplete v27 演进): 左右两栏(代码 50% + 名称 50%)，名称只读不可修改

**现状痛点**：v27 的 `<StockCodeAutocomplete>` 在 v-model 语义上**有缺陷**——
`update:modelValue` 在用户**打字未选**候选时就立即 emit 半选代码（例如输入 `"6005"` 就
emit `"6005"`），下游 `OrderForm.handleSubmit` 会拿着这个**非法未完成代码**走下单校验
或行情请求。这种"输入即值"的契约在交易场景下是危险的。

参考 user feedback（2026-07-13 16:39）：
> "这个组件就是为了输入证券代码的，确保输入的代码是有效的，同时，能展示代码和名称"

## 目标

1. **新增** `client/src/components/StockCodePicker.vue`，实现**严格语义**：
   - v-model 只在"从候选中真正选中"时 emit 非空值
   - 打字未选 → 输入框内可以打字，但**不污染 v-model**
   - **blur 时若输入框值 ≠ 已选 code，自动 emit('') 清空 v-model**
   - 这样下游(下单/查询/行情订阅)拿到的永远是真实验证过的代码

2. **保留 StockCodeAutocomplete.vue** —— 不破坏现有 4 个调用方的兼容；
   仅 `OrderForm.vue`（Trade.vue 下单入口）**首批试水**切换到新组件

3. **视觉 UX 强化**：右侧名称展示从"disabled el-input"改为 `el-tag`，
   "已选 / 未选"状态视觉差异更明显，未选时显示"请选择股票"占位

## 不在本次范围

- ❌ T0TaskCreateDialog.vue / StrategyConfig.vue / AdminStockConfig.vue —— 暂不切，
  按需后续单独迁移
- ❌ StockCodeAutocomplete.vue 删除 —— 保留作为兼容性兜底
- ❌ 后端 / 数据库 / REST 端点变化 —— 纯前端组件层
- ❌ cache 加载策略变化 —— 沿用 v25/v26 已落地的 `useStocksStore.cache`

## 风险

| 风险 | 缓解 |
|---|---|
| OrderForm 切换后, Trade.vue `@update:stock-code` 链路变化 | 保留 emit 转发 + 新增 `@blur` 兜底 emit('') |
| OrderForm.vue 中 `form.stock_name` 未及时清掉(显示陈旧) | `onStockCodeBlur` 检测 `!form.stock_code` 时同步清 `stock_name` |
| 误把"打字"过程 emit 给父组件 → QuotePanel 行情订阅抖动 | v28 内 `update:modelValue` emit 收紧到"真正选中 + blur 同步"两类 |
| 旧 StockCodeAutocomplete 残留 → 项目视觉不一致 | 文档明确调用方清单; 后续由独立 PR 全量切换 |

## commit 拆分

1. `feat(component)` `cce2bd9` — `client/src/components/StockCodePicker.vue` 新增 (commit 1)
2. `feat(orderform)` `d7a9ce1` — `OrderForm.vue` 切换到新组件试水 (commit 2)
3. `docs(openspec)` (commit 3) — 本 change 三件套(proposal / tasks / spec-deltas)
