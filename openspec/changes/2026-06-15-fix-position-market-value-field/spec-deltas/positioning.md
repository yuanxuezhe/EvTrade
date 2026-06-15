# Positioning — Spec Delta

## MODIFIED Requirements

### REQ-POS-001: Position ORM Schema (UPDATED)

The `positions` table **MUST** include the following columns (additions marked NEW):

| Column             | Type         | Notes |
|--------------------|--------------|-------|
| id                 | Integer PK   |       |
| trd_date           | String(8)    | YYYYMMDD |
| stock_code         | String(16)   |       |
| stock_name         | String(32)   |       |
| initial_position   | Integer      |       |
| today_buy          | Integer      |       |
| today_sell         | Integer      |       |
| available          | Integer      |       |
| total              | Integer      |       |
| cost               | Float        |       |
| **market_value**   | **Float**    | **NEW (2026-06-15) - nullable, populated by quote snapshots, NOT by reconcile** |
| synced_at          | DateTime     |       |
| synced_from        | String(16)   |       |

#### Scenario: market_value nullable for legacy rows
- **Given** existing rows in `positions` table created before 2026-06-15
- **When** ORM migration runs (drop + create)
- **Then** new `market_value` column exists with NULL default
- **And** legacy data is discarded (test environment only; production migration is out of scope)

#### Scenario: API prefers DB field, falls back to cost × total
- **Given** a position row with `market_value = NULL`
- **When** `GET /api/positions` returns it
- **Then** response `market_value = cost * total` (fallback for legacy data)
- **And** a position row with `market_value = 1234.5`
- **When** `GET /api/positions` returns it
- **Then** response `market_value = 1234.5` (DB field takes precedence)

#### Scenario: push handler writes market_value from snapshot, not calc
- **Given** a pos_cfm push arrives with `market_value` from quote feed
- **When** `services/push_handlers.py:222` updates the position
- **Then** `pos.market_value` is set to the push value
- **And** if push omits `market_value`, field is left unchanged (not zeroed)
