# Tasks: Fix v8 Single-Source Cache Violations

## 1. 改 Dashboard.vue
- [x] L226: `orderStore.trades` → `holdingsStore.trades`
- [x] L239: `orderStore.orders` → `holdingsStore.orders`
- (Dashboard.vue L183 `holdingsStore` 已 import，不需要再 import)

## 2. 改 Position.vue
- [x] L80 旁加 `import { useHoldingsStore } from '../stores/holdings'`
- [x] L85 旁加 `const holdingsStore = useHoldingsStore()`
- [x] L65: `:orders="orderStore.orders"` → `:orders="holdingsStore.orders"`
- [x] L66: `:trades="orderStore.trades"` → `:trades="holdingsStore.trades"`

## 3. 验证
- [x] 全项目 grep `orderStore\.(orders|trades|positions|asset)` = 0 matches
- [x] 浏览器访问 Dashboard 不再 TypeError
- [x] 浏览器访问 Position 不再 undefined

## 4. 提交
- [ ] feat(client): fix v8 single-source violations (2 files, +5/-4)
