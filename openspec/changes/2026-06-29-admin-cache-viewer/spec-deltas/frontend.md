# Spec Delta: frontend

## ADDED Requirements

### REQ-FE-101: Admin 缓存查看器 (CRUD)

> **新增** requirement。admin 专属页面，对 4 张 IDB 业务表做 CRUD，4 路由 + 1 通用表格组件。

The system SHALL provide an admin-only viewer with full CRUD (Create / Read / Update / Delete) on the 4 IDB business tables, available as 4 separate routes:

| Route | View | IDB Store | Allowed Ops |
|---|---|---|---|
| `/admin/cache/asset`     | `CacheAsset.vue`     | `asset`     | **Update only** (singleton 1 行) |
| `/admin/cache/positions` | `CachePositions.vue` | `positions` | CRUD + Clear |
| `/admin/cache/orders`    | `CacheOrders.vue`    | `orders`    | CRUD + Clear |
| `/admin/cache/trades`    | `CacheTrades.vue`    | `trades`    | CRUD + Clear (composite key [trd_date, trade_id]) |

All 4 routes have `meta.requiresAdmin: true` — non-admin users are redirected to `/` by the global router guard at [client/src/router/index.js](../../client/src/router/index.js).

The shared component is [client/src/components/CacheTableView.vue](../../client/src/components/CacheTableView.vue) — receives `storeName` + `fields` + `keyField` + `allowAdd/Delete/Clear` flags.

#### Scenario: 路由守卫

- **WHEN** non-admin user (role=trader / viewer) navigates to `/admin/cache/asset` (or any of the 4 cache routes)
- **THEN** router `beforeEach` guard redirects to `/` (silent — no error message)

#### Scenario: Sidebar 菜单

- **WHEN** admin user logs in
- **THEN** sidebar shows a "缓存查看" group with 4 sub-items (资金/持仓/委托/成交) — non-admin users do NOT see this group

#### Scenario: 资金表 (asset) 只允许改

- **WHEN** admin opens `/admin/cache/asset`
- **THEN** "新增" and "删" buttons are NOT shown (only "刷新" + "改" per row)
- **WHEN** admin edits the singleton row
- **THEN** `putItem('asset', {id: 'singleton', ...edited})` overwrites the single row

#### Scenario: 持仓 / 委托 / 成交表全 CRUD

- **WHEN** admin opens any of `/admin/cache/positions|orders|trades`
- **THEN** toolbar shows "刷新 / 清空 / 新增"; each row has "改 / 删" buttons
- **WHEN** admin clicks "清空"
- **THEN** `clearStore(storeName)` runs; on next API call (e.g. refresh data) the table repopulates from server

#### Scenario: 成交表 (trades) 复合主键

- **WHEN** admin edits or deletes a trade row
- **THEN** key is the array `[trd_date, trade_id]` (IDB composite key); both fields are disabled in the edit dialog

#### Scenario: 改动只影响本地

- **WHEN** admin performs any CRUD on the cache tables
- **THEN** changes are written to IDB only; NO server API call is made — this is a debugging/inspection tool, not a real data mutation path
