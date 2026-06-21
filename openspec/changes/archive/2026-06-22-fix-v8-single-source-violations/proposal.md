# Fix v8 Single-Source Cache Violations

## Why

REQ-FE-009 明确 `holdingsStore` 为 `orders / trades / positions / asset / activeTrdDate` 的**唯一权威**，
`orderStore` 在 v8 重构后**只暴露 actions**（不暴露上述 state 字段）。

但 Dashboard.vue:226/239 + Position.vue:65/66 共 4 处仍直接访问 `orderStore.{orders,trades,positions,asset}`，
违反规范。**症状已出现**：Dashboard.vue:226 `for (const t of orderStore.trades)` 报
`TypeError: orderStore.trades is not iterable` → render 崩溃 → SPA 白屏。

## What Changes

- **Dashboard.vue:226**: `for (const t of orderStore.trades)` → `for (const t of holdingsStore.trades)`
- **Dashboard.vue:239**: `const orders = orderStore.orders` → `const orders = holdingsStore.orders`
- **Position.vue:65**: `:orders="orderStore.orders"` → `:orders="holdingsStore.orders"`
- **Position.vue:66**: `:trades="orderStore.trades"` → `:trades="holdingsStore.trades"`
- **Position.vue**: 加 `useHoldingsStore` import + `const holdingsStore = useHoldingsStore()`

## Impact

- **受影响的 specs**: frontend/spec.md REQ-FE-009（增加 1.3 节：**禁止访问**）
- **受影响的代码**: 2 个 view 文件，4 处替换
- **测试**: 浏览器访问 Dashboard + Position 不再白屏

## Out of Scope

- `orderStore` 的 actions API 不变
- 后端 / WS / RPC 不变
- 其他 view 文件（Sidebar.vue 已修，commit 66ba63d）
