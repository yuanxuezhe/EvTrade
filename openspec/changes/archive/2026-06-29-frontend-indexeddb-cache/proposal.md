# 前端缓存：4 张业务表 → IndexedDB 持久化

> 创建日期：2026-06-29
> 状态：draft
> 范围：浏览器端，刷新后恢复业务数据

## Why

**用户诉求**："前端缓存如何保存在浏览器，使我可以在浏览器浏览缓存数据？每个缓存一个表存储"

**4 张业务表**（用户视角，不是 store 视角）:
- **资金** — 现金/冻结/市值/总资产
- **持仓** — 各标的的持仓量/成本/可用
- **委托** — 当日全部委托
- **成交** — 当日全部成交

**当前现状**（核查 [client/src/stores/](../client/src/stores/) 后）:
- 业务数据**纯内存**——刷新浏览器 → 4 表全部从 0 重新 fetch
- 已有零散 `localStorage` 引用（auth 存 token、ui 存偏好），但**业务数据没有持久化**
- v8 架构有"holdings store 是单一缓存源"约定（[client/src/stores/order.js:1-13](../client/src/stores/order.js)），**但**用户视角的"4 张表"在内存中实际分散在 holdings + asset + position 3 个 store 里

**问题**:
- 刷新瞬间 4 表数据空白（用户体感"白屏跳一下"）
- 网络抖动时 UI 完全没数据
- 开发者想"看缓存"只能加 console.log，无法在 DevTools 直接浏览

## What

引入 **IndexedDB** 作为业务缓存的二级存储：
- **每张业务表 = 一个 object store**（真正对应"每个缓存一个表"）
- 启动时一次性 rehydrate，运行时增量 write-through
- Schema 版本号守门，升级时**全量清空重灌**

### 4 张 object store + 1 张 meta

| Object Store | keyPath | 存的字段 | 来源内存位置 |
|---|---|---|---|
| `asset`     | `id` (固定 `'singleton'`) | `{cash, frozen_cash, market_value, total_asset}` | [client/src/stores/asset.js](../client/src/stores/asset.js) `asset.value` |
| `positions` | `stock_code` | 持仓字典（按 stock_code 主键）| [client/src/stores/holdings.js](../client/src/stores/holdings.js) `positions` + [client/src/stores/position.js](../client/src/stores/position.js) `positions` |
| `orders`    | `order_no` | 委托字典 | [client/src/stores/holdings.js](../client/src/stores/holdings.js) `orders` |
| `trades`    | `trd_date + trade_id` | 成交字典 | [client/src/stores/holdings.js](../client/src/stores/holdings.js) `trades` |
| `_meta`     | `key` | `{schema_version, last_rehydrate_ms, last_write_ms}` | 工具维护 |

> **key 设计原则**：用业务主键而不是递增 id，**支持 upsert by key**（ws push 增量更新时直接 put）
> **资金**虽然只有 1 行，仍然建独立 object store（而不是塞进 `_meta`），保持"每张表一 store"的对称性

### 持久化时机

| 触发 | 动作 | 位置 |
|---|---|---|
| App 启动 / 登录后 | 从 IDB rehydrate → 写回对应 store | [client/src/main.js](../client/src/main.js) 启动序列 |
| `fetchAsset()` 完成 | clear + bulkPut 资金表 | [client/src/stores/asset.js](../client/src/stores/asset.js) `fetchAsset()` 末尾 |
| `fetchPositions()` 完成 | clear + bulkPut 持仓表 | [client/src/stores/position.js](../client/src/stores/position.js) `fetchPositions()` 末尾 |
| `bootstrap()` 完成 | clear + bulkPut 委托 + 成交表 | [client/src/stores/holdings.js](../client/src/stores/holdings.js) `bootstrap()` 末尾 |
| ws push applyXxx 完成 | **upsert by key** 增量写 | [client/src/stores/holdings_push.js](../client/src/stores/holdings_push.js) 5 个 apply* 末尾 |
| `applyOrderPush` | upsert 到 `orders` | 同上 |
| `applyTradePush` | upsert 到 `trades` | 同上 |
| `applyPositionPush` | upsert 到 `positions` | 同上 |
| `applyAssetPush` | put 到 `asset` | 同上 |

> **关键约束**：IDB 写入**不影响** Pinia 内存；只是把内存快照"备份"一份。读路径不变（仍走 Pinia），IDB 只在启动时 rehydrate 一次。

### 依赖

- [`idb`](https://www.npmjs.com/package/idb) v8+（IndexedDB Promise 封装，~5KB）
- 写入 [client/package.json](../client/package.json) `dependencies`

### Schema 版本策略（用户选"全量清空"）

- IDB name: `evtrade-cache`
- `_meta.schema_version` 启动时核对，**不匹配 → `deleteDatabase()` 重灌**
- 未来升级时改 [client/src/utils/idbStore.js](../client/src/utils/idbStore.js) 的 `SCHEMA_VERSION` 常量即可
- **不写迁移函数**——用户选"简单粗暴"

### DevTools 浏览（用户选"手动看"）

打开 Chrome DevTools → Application → IndexedDB → `evtrade-cache` → 5 个 object store。
- `asset` 1 行
- `positions` / `orders` / `trades` 多行
- `_meta` 3 行

**不做调试页面**。

## 不做什么

- 不做 IndexedDB → server 反向同步（缓存是只读快照）
- 不做数据加密（业务数据非敏感；token 已有专门方案）
- 不做 LRU 淘汰（容量足够）
- 不做调试页面 / 导出 JSON
- 不持久化 auth / ui / ws_heartbeat / quote

## 影响的 capability

- `frontend` — 新增 spec requirement "业务数据 IndexedDB 持久化"
- `dev-process-control` — 启动序列增加 rehydrate 步骤

## 验证

- 启动 → 加载 → 刷新浏览器 → 看到 4 表立即从缓存恢复
- 触发 ws push → 关闭浏览器 → 重开 → 推送的最终态保留
- 改 `SCHEMA_VERSION = 2` → 刷新 → DevTools 看到 IDB 被重建
- `npm run dev` 启动正常，无 IDB 错误日志
- `npm test` 现有用例不挂
