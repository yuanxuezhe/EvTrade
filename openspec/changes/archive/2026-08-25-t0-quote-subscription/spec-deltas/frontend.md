# frontend spec delta — 2026-08-25-t0-quote-subscription

## ADDED Requirements

### REQ-FE-538: useQuoteSubscription composable 契约（2026-08-25）

**业务定位**: 抽取"自动订阅 quote + 自动 unsubscribe" 模式为 composable，统一 3 个调用方（T0Trade / StkPoolView / QuotePanel），避免重复 race-condition 代码。

**接口契约**:

```js
// client/src/composables/useQuoteSubscription.js
export function useQuoteSubscription(codesGetter: () => string[] | Ref<string[]>): {
  codes: ComputedRef<string[]>  // 去重 + 过滤 falsy 后的当前 codes
}
```

**行为契约**:

1. **自动 subscribe**: codesGetter 返回值变化时（如表格 rows 变化），diff 旧/新 codes → 自动 `quoteStore.subscribe(added)` + `quoteStore.unsubscribe(removed)`
2. **自动 unsubscribe**: `onBeforeUnmount` 时自动 `quoteStore.unsubscribe([...currentCodes])`
3. **去重**: 用 `Array.from(new Set(...))` 去重（同一 code 多次出现只订阅 1 次）
4. **过滤 falsy**: `filter(Boolean)` 跳过 null/undefined/空串
5. **flush: 'post'**: watch 用 `flush: 'post'`，避让 v-for 渲染同步挂载的竞争
6. **不感知跨页面订阅**: diff 算法只管自己的 codes；多页面订阅同一 code 时 unsubscribe 不会误影响其他页面（靠 quoteStore.subscribedSet 全局去重）

#### Scenario: T0Trade.vue 任务列表接入（修主问题）

- **GIVEN** user 进入 "快速做T" 页面（T0Trade.vue）
- **AND** taskRows 包含 N 个 stock_code（如 ["600030.SH", "000001.SZ"]）
- **WHEN** 页面挂载
- **THEN** composable 立即 `quoteStore.subscribe(["600030.SH", "000001.SZ"])`
- **AND** ws_manager 为这 2 个 code 触发 quote_update 推送
- **AND** LivePriceCell 实时显示最新价

#### Scenario: 切换 task 筛选（订阅 diff）

- **GIVEN** T0Trade 页面已挂载，taskRows 当前 ["600030.SH"]
- **WHEN** 切换 task 筛选，taskRows 变为 ["000001.SZ"]
- **THEN** composable 自动 `quoteStore.unsubscribe(["600030.SH"])` + `quoteStore.subscribe(["000001.SZ"])`
- **AND** 不重发仍在订阅的 code（diff 算法）

#### Scenario: 离开页面（无幽灵订阅）

- **GIVEN** T0Trade 页面已挂载，taskRows ["600030.SH", "000001.SZ"]
- **WHEN** user 离开页面（路由跳转 / 关闭 tab）
- **THEN** `onBeforeUnmount` 触发 composable 自动 `quoteStore.unsubscribe(["600030.SH", "000001.SZ"])`
- **AND** 后端 ws_manager 不再为这 2 个 code 推 quote_update

#### Scenario: 多页面订阅同一 code（不互相影响）

- **GIVEN** T0Trade 页面订阅 ["600030.SH"] + StkPoolView 同时订阅 ["600030.SH", "600519.SH"]
- **WHEN** T0Trade 页面卸载
- **THEN** StkPoolView 的 "600030.SH" 仍订阅（composable 各自 unsubscribe 自己的 codes，quoteStore.subscribedSet 全局去重）
- **AND** StkPoolView 的 "600519.SH" 也仍订阅

#### Scenario: codes 为空数组（边界）

- **GIVEN** taskRows 为空数组
- **WHEN** composable 初始化
- **THEN** 不调 subscribe（codes 空数组时直接跳过）
- **AND** onBeforeUnmount 也不调 unsubscribe（lastCodes 为空）

#### Scenario: race-condition（async 数据加载）

- **GIVEN** 调用方用 `let unmounted = false` flag 管自己的 async 竞态（如 StkPoolView 的 `loadPools` / `loadDetail`）
- **WHEN** 调用方在 unmount 后仍尝试 `quoteStore.subscribe(...)`
- **THEN** composable 不管这个竞态（行为不变，调用方自己 guard）
- **AND** 已有 `if (unmounted) return` 检查防御

**调用方列表（v1）**:

| 文件 | 用法 | 状态 |
|---|---|---|
| `client/src/views/T0Trade.vue` | `useQuoteSubscription(() => taskRows.value.map(r => r.stock_code))` | 修主问题 |
| `client/src/views/StkPoolView.vue` | `useQuoteSubscription(() => detail.value.map(d => d.stock_code))` | 行为不变重构 |

**v1 不重构 QuotePanel** (因接口不兼容):

`QuotePanel.vue:170-185` 有 3 处特殊行为与 v1 composable 接口不完全等价：
- 300ms debounce (用户连输字符时避免每个字符都发订阅)
- 清空时不 unsubscribe (保留订阅, props.stockCode='' 时继续展示旧数据)
- `_currentCode` 局部非 reactive 状态

v1 composable 接口 (薄封装 + 即时 diff + 自动 unsubscribe) 跟 QuotePanel 上述行为不直接对齐。后续若需重构可加 `debounceMs` + `keepOnEmpty` 选项。**本次不强行替换**（CLAUDE.md § 九 最小改动原则）。

**不在范围（v1 不做）**:

- ❌ 内置 unmounted flag（调用方各自管 async 竞态）
- ❌ 节流 / 防抖（codes 变化频率低，股票池切换是个位数秒级）
- ❌ 自动重连重订阅（已有 quoteStore.replayAll，由 ws_heartbeat 在重连后调）
