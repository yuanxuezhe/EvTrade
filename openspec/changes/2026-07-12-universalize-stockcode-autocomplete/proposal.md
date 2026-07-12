# Proposal: StockCodeAutocomplete 通用化 + 下单入口接入

**Change ID**: `2026-07-12-universalize-stockcode-autocomplete`
**Date**: 2026-07-12
**Status**: Proposed

## 背景

v25 (2026-07-12-stocks-cache-and-short-name) 已实现：
- `client/src/stores/stocks.js` 维护全量 5529 行 cache
- `client/src/components/StockCodeAutocomplete.vue` 在 AdminStockConfig 编辑弹窗中实现
  三路筛选（stock_code / stock_name / short_name）
- 用户问题（2026-07-12 16:37）：**交易下单页面输入股票代码，没有提示候选**

现状：下单入口（`OrderForm` / `T0TaskCreateDialog` / `StrategyConfig`）使用 `el-input` +
手动输入校验，没有 autocomplete，**易输错且不知道选哪个**。

## 目标

1. **StockCodeAutocomplete 通用化** —— 增强组件，支持：
   - `@select` 事件（候选被选中时通知父组件）
   - 暴露完整候选 stock 对象（含 `stock_name`/`short_name`/`sector` 等）
   - `size` prop 透传（适配表单行）
   - 错误降级（cache 加载失败时 input 仍可手动输入）

2. **3 个下单入口替换**：
   - `client/src/components/OrderForm.vue`（交易下单股票代码输入，必换）
   - `client/src/components/trade/T0TaskCreateDialog.vue`（快速做T股票选择）
   - `client/src/modules/strategy/StrategyConfig.vue`（策略交易股票代码）

3. **全局预加载 cache** —— App 启动即后台加载 5529 行，**进入 Trade 页 0 等待**

## 不在本次范围

- `CachePositions.vue`（disabled 调整表单，不适用）
- `HistoryOrders.vue` / `HistoryTrades.vue`（查询筛选，可选留待 v27）
- 新增 REST 端点（autocomplete 纯前端实现，不动后端）

## 风险

- 替换 3 个组件各 ~50 行 diff，需逐文件验证父组件绑定 (`@update:stock-code` 等) 兼容
- 全局预加载时可能影响首次首屏（白屏 ~18s）→ 用 lazy + 浏览器缓存降低风险
- autocomplete 选中时 el-autocomplete 触发 `@select`；用户纯手动输入不触发 `@select`
  → 用 `watch(modelValue)` 覆盖两种情况

## commit 拆分

1. `chore(openspec)` 4 件套
2. `feat(client)` StockCodeAutocomplete 增强
3. `feat(client)` 替换 3 个下单入口
4. `feat(client)` 全局预加载 cache