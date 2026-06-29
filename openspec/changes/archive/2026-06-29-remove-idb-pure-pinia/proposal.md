# 去掉 IDB, 纯 Pinia 内存架构

> 创建日期：2026-06-29
> 状态：draft
> 范围：撤销全部 IDB 持久化，回到纯 Pinia 内存 + admin 缓存查看器直读 Pinia

## Why

**用户报**："IDB 变了，Pinia 没变"

经过几轮反复讨论，用户最终决定：

> 去掉 IDB，缓存页面直接读取 pinia 内存中的数据。修改缓存页面，就直接改 pinia 数据。页面加载数据的时候，直接通过接口查询服务端数据库的数据。修改缓存页面只为了前端调试使用，不要更改服务端数据库数据

**核心问题**：IDB + Pinia 双层存储引发的同步复杂度（之前踩了 3 个坑：`bulkPut` 不存在、Proxy 不可克隆、getter/setter 不可克隆），对一个"调试用工具"严重过度设计。

**回归后的优势**：
- **零同步问题**：业务页面读 Pinia，cache-viewer 改 Pinia → Vue 响应式自动让业务页面看到
- **零 IDB 包袱**：脱壳、事务、structured clone 全部消失
- **admin cache-viewer 真正"调试用"**：改 Pinia 不影响 server（之前 IDB 路径可能写穿透到 server 反向恢复）

## What

### 删除

| 文件 | 原因 |
|---|---|
| [client/src/utils/idbStore.js](../../client/src/utils/idbStore.js) | IDB 封装（putItem / bulkReplace / getAll 等） |
| [client/src/utils/cacheRehydrate.js](../../client/src/utils/cacheRehydrate.js) | 启动 rehydrate |
| [client/src/utils/](../../client/src/utils/) 目录 | 可保留，但只剩 format.js |
| `client/package.json` 的 `"idb": "^8.0.3"` 依赖 | 不再需要 |
| `client/package-lock.json` 中 idb 相关 | `npm uninstall idb` 时自动清 |

### 改动 store

| 文件 | 删除/改 |
|---|---|
| [client/src/main.js](../../client/src/main.js) | 删 `rehydrateFromIDB().finally(() => app.mount())` 调用，回归 `app.mount('#app')` |
| [client/src/stores/asset.js](../../client/src/stores/asset.js) | `fetchAsset` 末尾的 `bulkReplace('asset', ...)` + `touchLastWrite()` 全删 |
| [client/src/stores/position.js](../../client/src/stores/position.js) | `fetchPositions` 末尾的 `bulkReplace('positions', ...)` 全删 |
| [client/src/stores/holdings.js](../../client/src/stores/holdings.js) | `bootstrap` 末尾的 `bulkReplace('orders', ...)` + `bulkReplace('trades', ...)` 全删；`refreshAll` 末尾的同款全删 |
| [client/src/stores/holdings_push.js](../../client/src/stores/holdings_push.js) | 5 个 apply* 末尾的 `putItem(...)` 全删（push 只改 Pinia） |

### 改动 cache-viewer

[client/src/components/CacheTableView.vue](../../client/src/components/CacheTableView.vue) **整体重写**：
- 不再调 `getAll / putItem / deleteItem / clearStore`（这些都来自 idbStore）
- 直接接 `useAssetStore / usePositionStore / useHoldingsStore` 等 Pinia store
- 改用 `storeToRefs(store)` 读 ref，`store.xxx = newValue` 改
- 删 `@changed` emit（**不再需要**——同源 ref，Vue 响应式自动传播）
- 删 `_toPlain`（不再是 IDB 写入，避免 Proxy 克隆问题）
- props 改为：接收 `storeRef` + `keyField` + `fields` + 操作标志位

4 个 page view 简化为提供 store 来源和 keyField。

### 改 SPEC

[client/src/stores/holdings.js](../../client/src/stores/holdings.js) 的 v8 注释 "holdings store 是单一缓存源" 仍然正确——Pinia 仍是内存主存，cache-viewer 操作同一份 ref。

[openspec/specs/frontend/spec.md REQ-FE-100](../../openspec/specs/frontend/spec.md) **整体移除**（"业务数据 IndexedDB 持久化" 不再适用），增补"业务数据纯内存"scenario。

## 不做什么

- 不重写业务页面（Holdings/Orders/Trades 等）—— 它们读 Pinia，cache-viewer 改同一份 ref，**自动同步**
- 不动 ws push 协议（push 仍只改 Pinia）
- 不动 server API
- 不改 sidebar 菜单 / router（cache-viewer 4 路由保留）
- 不删 admin cache-viewer（仍是 admin 工具，但数据源从 IDB 切到 Pinia）

## 验证

- 启动 → 业务页面先空 → bootstrap 拉 server 数据填充 → 正常显示
- admin 登录 → 侧栏 "缓存查看" 4 子项 → 表格显示当前 Pinia 数据
- 在 cache-viewer 改一行 → 立即跳到对应业务页面 → **新数据已显示**（同源 ref 自动响应）
- 在 cache-viewer 清空一张表 → 业务页面也立即空（再次验证同源）
- ws push 来 → 业务页面正常更新（与之前一致）
- 刷新浏览器（F5）→ 业务页面短暂空白 → bootstrap 重灌（这是**预期行为**，"调试用"工具不持久化）
- `npm run dev` 启动无 IDB 相关错误
- `npm run build` 编译通过

## 影响的 capability

- `frontend` — REQ-FE-100（IDB 持久化）**整体删除**；REQ-FE-101（admin cache-viewer）修改数据源为 Pinia
