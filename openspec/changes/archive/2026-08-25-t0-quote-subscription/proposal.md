# 2026-08-25-t0-quote-subscription — T0Trade 任务列表订阅行情 + useQuoteSubscription 抽取

## Why

**用户反馈**：进入 "快速做T" 页面（T0Trade.vue）后，**任务列表里 N 个证券代码的最新价（last_price 列）始终不推送**——LivePriceCell 组件用了但永远显示空/默认值；同一页面持仓面板 HoldingsPanel 内的标的能正常显示最新价。

### 根因（已实测）

`client/src/views/T0Trade.vue:160-163` 主表 `last_price` 列模板：

```vue
<template #column-last_price="{ row }">
  <!-- 通用 LivePriceCell (与 HoldingsPanel / CachePositions 三处一致) -->
  <LivePriceCell :stock-code="row.stock_code" />
</template>
```

`LivePriceCell` 内部读 `quoteStore.getLastPrice(row.stock_code)`。

但 `T0Trade.vue` 的 `<script setup>` **全程未调用过** `quoteStore.subscribe(...)`：

- 第 384 行 `const quoteStore = useQuoteStore()` —— 仅实例化
- 第 388 行 `const { positions } = storeToRefs(holdingsStore)` —— 也不传 `quoteStore`
- 整个 setup 里 `grep -n 'quoteStore\.' T0Trade.vue` 找不到 `.subscribe(` / `.unsubscribe(` 调用

对比 `client/src/views/StkPoolView.vue`（**教科书式正确写法**）：
- L140 `quoteStore = useQuoteStore()`
- L149 `detailCodes = computed(...)` 派生订阅列表
- L180-186 `onBeforeUnmount → quoteStore.unsubscribe(detailCodes)`
- L216-220 `loadDetail → quoteStore.subscribe(codes)`
- L230-241 `switchPool → unsubscribe(旧) + loadDetail + subscribe(新)`

**结论**：T0Trade.vue 任务列表里那些 stock_code 从来不在 `quoteStore.subscribedSet` 内 → 后端 `ws_manager['quote_update']` 不为这些 code 触发推送 → 前端 quote store 没数据 → LivePriceCell 永远空。

### 业务影响

T0 任务列表里"最新价(涨跌幅)"+"做T总盈亏"+"当日做T盈亏" 三列都依赖实时行情：
- `t0PnlCell()` 读 `quoteStore.getField(code, LAST)` → 无 tick → 永远 0
- 用户看不到做T 当日盈亏实时变化 → 失去做T 决策的核心数据

### 修复策略

**抽取 `useQuoteSubscription(codesGetter)` composable**，把 StkPoolView 4 段重复模式封装成可复用接口，3 个调用方统一接入：

1. **T0Trade.vue**（修主问题 + 接入 composable）
2. **StkPoolView.vue**（行为不变，重构到 composable）
3. **QuotePanel.vue:180**（line 180 那 1 处 `quoteStore.subscribe([c])`）

## What

### 1. 新建 composable

`client/src/composables/useQuoteSubscription.js` (~50 行)

```js
export function useQuoteSubscription(codesGetter) {
  // 自动: codes 变化 → diff 旧/新 → subscribe(new) + unsubscribe(removed)
  // 自动: onBeforeUnmount → unsubscribe(current)
  // 返回 codes (去重 + 过滤后的当前 codes)
}
```

**核心设计**：
- diff 算法只动自己的 codes（不感知跨页面订阅），靠 `quoteStore.subscribedSet` 全局去重
- `flush: 'post'` 让 watch 延迟到 DOM 更新后，避让 v-for 同时挂载的竞争
- 不内置 `unmounted` flag（调用方继续管自己的 async 竞态）

### 2. 改动 2 个调用方（T0Trade 主问题修复 + StkPoolView 行为不变重构）

| 文件 | 改动 | 行为变化 |
|---|---|---|
| `T0Trade.vue` | 加 composable 调用（1 行） | **✅ 主问题修复**（任务列表有实时价） |
| `StkPoolView.vue` | 4 段订阅替换成 composable（行为不变） | 行为不变（删除 6 行手写代码） |

**不在 v1 重构范围**: `QuotePanel.vue`（line 180）有自己的 300ms debounce + "清空时不 unsubscribe — 保留订阅" 行为，跟 useQuoteSubscription diff 算法不兼容。后续如有需要可单独改（diff 算法加 debounce 选项）。

### 3. spec delta

`openspec/specs/frontend/spec.md` 新增 **REQ-FE-538：useQuoteSubscription composable 契约**。

## 涉及 capability

| Cap | 改动 | spec 文件 |
|---|---|---|
| `frontend` | 新增 composable + 3 处接入 | `openspec/specs/frontend/spec.md` REQ-FE-538 |

## 不在范围（避免 scope creep）

- ❌ 改 quoteStore.subscribe 内部（行为已正确，>100 自动全市场订阅已有）
- ❌ 改 LivePriceCell（组件本身 OK，缺数据是订阅问题）
- ❌ T0TaskDetail.vue 内的行情订阅（如有，按需后续 change）
- ❌ 其他 view（如 QuotePanel 外的页面）—— 暂未发现相同 bug

## 验证

1. **进入 T0Trade 页面** → DevTools Network ws 帧应包含 `{"type":"subscribe","codes":["600030.SH",...]}`（taskRows 里的 stock_code）
2. **任务列表 last_price 列** → LivePriceCell 实时刷新（点 ws 帧应见 `{"channel":"quote_update","data":{"stock_code":"...","last_price":...}}`）
3. **切换 task 筛选** → ws 帧见 `unsubscribe([old])` + `subscribe([new])`（diff 算法生效）
4. **离开 T0Trade 页面** → ws 帧见 `unsubscribe([all])`（无幽灵订阅）
5. **StkPoolView / QuotePanel** → 现有功能回归测试无变化
6. `npm run build` 通过（CLAUDE.md § 八）
7. `pytest hq/ server/tests/` 基线不掉（CLAUDE.md § 八：71 collected / 64 passed 不掉）

## 风险

- **极低**：composable 是薄封装，行为与 StkPoolView 现有 4 段一致
- **diff 算法边界**：跨页面订阅同一 code 时，A 页面 unsubscribe 不会影响 B 页面（靠 subscribedSet 全局去重）—— 已在 quoteStore.subscribe 内部实现

## 参考

- `client/src/views/StkPoolView.vue:140-241`（教科书模式）
- `client/src/stores/quote.js:171-198`（subscribe/unsubscribe 契约）
- `client/src/composables/useT0OrderSubmit.js`（同目录 composable 范例）
- `openspec/specs/frontend/spec.md` REQ-FE-538 新增段
- 知识库/前端/ 行情订阅相关段
