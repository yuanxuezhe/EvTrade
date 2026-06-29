# Spec Delta: frontend

## MODIFIED Requirements

### REQ-FE-101: Admin 缓存查看器 (CRUD)

#### Scenario: 改动只影响本地

- **WHEN** admin performs any CRUD on the cache tables
- **THEN** changes are written to IDB only; NO server API call is made — this is a debugging/inspection tool, not a real data mutation path

#### Scenario: IDB 改动后通知业务页面刷新

- **WHEN** admin performs put / delete / clear in the cache viewer
- **THEN** `CacheTableView` emits `changed` event; the 4 page views handle it by calling corresponding store's `fetchAsset` / `fetchPositions` / `refreshAll`, which re-fetches from server and updates Pinia in-memory state
- **AND** business pages (e.g. `Holdings.vue`, `Orders.vue`) which read from Pinia immediately see the latest data without page refresh
- **NOTE**: server data overwrites the admin's local IDB edits (server is the source of truth on next refresh); if persistence of admin edits is needed, a separate "override layer" design is required (out of scope)
