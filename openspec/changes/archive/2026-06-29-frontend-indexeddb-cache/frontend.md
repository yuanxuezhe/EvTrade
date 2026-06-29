# Spec Delta: frontend

## ADDED Requirements

### REQ-FE-100: 业务数据 IndexedDB 持久化

> **新增** requirement。前端 4 张业务表（资金/持仓/委托/成交）持久化到 IndexedDB，刷新浏览器后从 IDB 恢复，避免空白闪烁。

The system SHALL persist 4 business data tables to IndexedDB to enable instant restore on page refresh:
- 资金 (asset)
- 持仓 (positions)
- 委托 (orders)
- 成交 (trades)

#### Scenario: 启动恢复

- **WHEN** user opens the app and is authenticated
- **THEN** `main.js` triggers `rehydrateFromIDB()` BEFORE `app.mount()`, which:
  1) opens `evtrade-cache` IDB
  2) checks `_meta.schema_version` — if mismatch, deletes and recreates the database
  3) reads 4 object stores in parallel (`asset` / `positions` / `orders` / `trades`)
  4) writes data back to corresponding Pinia stores
  5) rehydrate failures degrade silently (Pinia uses initial empty values)

#### Scenario: API 写透 (write-through)

- **WHEN** `fetchAsset()` / `fetchPositions()` completes successfully
- **THEN** the fetched data is written to IDB via `bulkReplace(storeName, items)` after Pinia state updates

#### Scenario: WS 推送增量写

- **WHEN** ws push handler (e.g. `applyOrderPush`) merges a row into Pinia state
- **THEN** the merged row is upserted to IDB by primary key (stock_code / order_no / [trd_date, trade_id]) via `putItem()`
- `applyQuote` does NOT persist (quote is real-time, not cached)

#### Scenario: Schema 升级 (全量清空)

- **WHEN** `SCHEMA_VERSION` constant in `idbStore.js` is incremented
- **THEN** on next DB open, `_meta.schema_version` mismatch triggers `deleteDB('evtrade-cache')` and recreates all 5 object stores fresh; user sees empty tables until next API call refills

#### Scenario: 不持久化的 store

- **WHEN** considering other Pinia stores
- **THEN** `auth` / `ui` / `ws*` / `quote` are NOT persisted (auth already handled by JWT, others are runtime state)

#### Scenario: DevTools 浏览

- **WHEN** developer wants to inspect cached data
- **THEN** open Chrome DevTools → Application → IndexedDB → `evtrade-cache` → 5 object stores visible (asset / positions / orders / trades / _meta)
