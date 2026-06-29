# Admin 缓存查看器 (IDB CRUD)

> 创建日期：2026-06-29
> 状态：draft
> 范围：admin-only 前端页面，操作 4 张 IDB 表

## Why

延续 [2026-06-29-frontend-indexeddb-cache](../archive/2026-06-29-frontend-indexeddb-cache/) 的"4 张业务表入 IDB"——IDB 已有数据后，需要一个**管理员可访问**的可视化页面，支持 CRUD：

- **开发期**：排查"为什么 4 表的数据不对"（脏数据、漏写、key 冲突）
- **应急**：清空某张表、删除脏记录、强制覆盖
- **演示**：在 DevTools 之外用更友好的 UI 验证持久化逻辑

当前 IDB 只能 DevTools → Application → IndexedDB → 手工操作，效率低、易出错。

## What

新增 4 个 admin-only 路由 + 1 个通用表格组件：

| 路由 | 视图 | 鉴权 | 操作 |
|---|---|---|---|
| `/admin/cache/asset` | CacheAsset.vue | admin | **只改**（singleton 1 行） |
| `/admin/cache/positions` | CachePositions.vue | admin | 增 / 改 / 删 / 清空 |
| `/admin/cache/orders` | CacheOrders.vue | admin | 增 / 改 / 删 / 清空 |
| `/admin/cache/trades` | CacheTrades.vue | admin | 增 / 改 / 删 / 清空 |

通用组件：[client/src/components/CacheTableView.vue](../client/src/components/CacheTableView.vue) — 接收 `storeName` + 字段定义，渲染 el-table + 工具栏（刷新 / 清空 / 新增）+ 增改 dialog + 删除确认。

导航：[AppHeader.vue](../client/src/AppHeader.vue) 在 admin 区加子菜单"缓存查看 → 资金 / 持仓 / 委托 / 成交"。

### 关键约束（用户拍板）

1. **只改本地 IDB**，**不调 server API**——增删改都在浏览器本地，不上报
2. **资金表只允许改**——业务上只 1 行
3. **4 独立路由 + 4 个 page**（不是单页 tab）——与 admin 已有 `/system-init` `/system-config` 风格一致
4. **AppHeader 加菜单项**——admin 可见

### 不做什么

- 不持久化到 server（按用户选"只改本地"）
- 不做 schema_version 迁移入口（升级时改 SCHEMA_VERSION 即可）
- 不做数据导入/导出（避免被滥用为攻击入口）
- 不做编辑历史 / undo（应急工具，不复杂化）

## 影响的 capability

- `frontend` — 新增 spec requirement "admin 缓存查看器"
- `dev-process-control` — 不影响启动序列

## 验证

- admin 登录 → 看到菜单"缓存查看"4 个子项
- viewer / trader 登录 → 看不到菜单；直接访问 URL → 路由守卫跳走
- 4 页加载 → 表格显示当前 IDB 数据
- 改一行 → 立即看到表格更新；**关键** → 关闭浏览器 → 重开 → 数据保留（说明 write-through 双向 OK）
- 清空表 → 表格空；触发 refresh → 数据从 server 重新灌入
- 新增一条脏数据 → 表格出现；关闭浏览器 → 重开 → 仍存在（说明单条 put 双向 OK）
- 删除一条 → 表格减少；关闭浏览器 → 重开 → 不存在
