# Cache 查看器: 改 IDB 后通知 Pinia 刷新

> 创建日期：2026-06-29
> 状态：draft
> 范围：CacheTableView.vue + 4 page view

## Why

**用户报**："为什么缓存页面修改了持仓缓存数据后，在持仓查询页面刷新没有更新数据？"

**根因诊断**（[systematic-debugging](skills/systematic-debugging) 步骤 1-2）：

| 层 | 状态 |
|---|---|
| 1. 用户的"刷新"是浏览器 F5 还是路由切换？ | 两种都试过，都不更新 |
| 2. [Holdings.vue](../../client/src/views/Holdings.vue) 数据源 | 第 128 行 `get: () => holdingsStore.positions` — **走 Pinia 内存** |
| 3. cache-viewer 改 IDB 时是否更新 Pinia？ | ❌ [CacheTableView.vue](../../client/src/components/CacheTableView.vue) 只调 `putItem` / `deleteItem` / `clearStore`，**完全没 import 任何 store** |
| 4. 路由切换是否触发 rehydrate？ | ❌ [main.js](../../client/src/main.js) 的 `rehydrateFromIDB()` 只在 App 启动时跑一次 |

**结论**：cache-viewer 改 IDB 后，Pinia `holdingsStore.positions` / `orders` / `trades` / `asset` 内存里**还是旧数据**。`Holdings.vue` 读 Pinia → 看到旧数据。即使手动 F5 刷新页面，也只是**重新跑 main.js 启动序列**——但 `holdingsStore` 紧接着的 `bootstrap()` 会**从 server 重新拉数据**（不是从 IDB 读），所以会**覆盖**刚刚 IDB 的修改！

更糟糕：**bootstrap 会写 IDB（write-through）→ 把 IDB 里 admin 改的数据又覆盖回 server 来的数据**。

## What

`CacheTableView.vue` 在 put/delete/clear 成功后**立即 emit `changed` 事件**。4 个 page view 接 `changed` 后调对应 store 的 `refreshXxx()` / `fetchXxx()`：

| 页面 | store action |
|---|---|
| CacheAsset.vue | `useAssetStore().fetchAsset()` |
| CachePositions.vue | `usePositionStore().fetchPositions()` + `useHoldingsStore().positions = pos` (v8 单一源) |
| CacheOrders.vue | `useHoldingsStore().refreshAll()` (orders 没独立 fetch) |
| CacheTrades.vue | `useHoldingsStore().refreshAll()` (trades 同上) |

### 设计

1. **emit 走 `changed` 不带 payload** — 父组件**不直接改 store**，由 page view 自己决定怎么 refresh（asset 简单 fetchAsset 即可；positions 要双写 holdings.positions）
2. **put/delete/clear 三个地方都 emit** — 不漏任何 IDB 改动
3. **emit 在 IDB 写成功之后** — 失败不 emit（避免 IDB 失败但 store 被刷新成 server 数据，反而更糟）

### 不做什么

- 不让通用组件**直接**调 store（破坏通用性，依赖反转）
- 不改 `rehydrateFromIDB` 启动逻辑（不解决根因，且会引入"路由切换重灌"等新问题）
- 不在 put/delete/clear 时手动修改 Pinia 内存（容易跟 store 内部逻辑冲突；走 refresh 才是单一路径）

## 影响的 capability

- `frontend` — REQ-FE-101 新增 1 scenario

## 验证

- 在 `/admin/cache/positions` 改一行 → 立即跳到 `/holdings` → **持仓数据已更新**（不再等下次 bootstrap）
- 在 `/admin/cache/orders` 删一行 → 立即跳到 `/orders` → 该委托消失
- 在 `/admin/cache/asset` 改现金金额 → 立即跳到 `/asset` → 总资产更新
- console 不应再看到"IDB write-through 失败"以外的异常
- 4 page view 的 `load()` 仍然要能跑（init mount 时）

## 注意

> **这次 fix 揭示了一个更深的架构问题**：用户改 IDB 后又触发了 `fetchPositions` / `refreshAll`——这会**从 server 重新拉数据，再 write-through 回 IDB，覆盖掉 admin 的修改**。
>
> 但**当前需求**是 admin 排查脏数据 → 改 IDB → 看效果。**让 admin 看到 server 当前数据**反而合理（如果 server 与 IDB 不一致，server 是真相）。
>
> 真正"IDB-only 编辑"是另一个需求（持久化 admin 改动），需要新设计：把 IDB 改成"覆盖层"或"补丁层"。**当前 change 不实现**，仅留后续讨论。
