# REQ-FE-009: v8 Single-Source Cache

## ADDED Requirements

### REQ-FE-009.3 (禁止访问)

- **MUST NOT** access `orderStore.{orders, trades, positions, asset, activeTrdDate}` from any view.
- **MUST** use `useHoldingsStore()` for the above state.
- `orderStore` exposes **only actions** (`placeOrder`, `cancelOrder`, etc.) and read-only helpers
  that do not duplicate holdings state.

#### Scenario

Given a view component imports `useOrderStore`
When accessing `orderStore.orders` / `orderStore.trades` / `orderStore.positions` / `orderStore.asset`
Then v8 single-source guard should report 4 violations and rename to `holdingsStore.{...}`.
