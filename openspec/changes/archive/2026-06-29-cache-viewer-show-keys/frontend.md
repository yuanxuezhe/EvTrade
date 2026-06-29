# Spec Delta: frontend

## MODIFIED Requirements

### REQ-FE-101: Admin 缓存查看器 (CRUD)

> **新增** scenario（不改原 requirement 文本）

#### Scenario: 列名带英文 key 后缀

- **WHEN** admin views any cache table (header or edit dialog form-item)
- **THEN** each column label renders as `"中文 (english_key)"` e.g. `现金 (cash)`, `总资产 (total_asset)` — so admin can directly map displayed column to the actual IDB key without consulting the schema separately
