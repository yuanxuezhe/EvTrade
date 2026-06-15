# SystemInit & Users API — Spec Delta

## MODIFIED Requirements

### REQ-INIT-001: SystemInit Page Data Loading (UPDATED)

The SystemInit page **MUST** load all status data on mount via 3 parallel requests:

- **REQ-INIT-001.1**: GET /api/admin/trading-day/active
  (single TradingDayOut or null; 返 current active day)
- **REQ-INIT-001.2**: GET /api/admin/trading-day?days=90
  (List[TradingDayOut]; 历史 90 天)
- **REQ-INIT-001.3**: GET /api/admin/trading-session
- **REQ-INIT-001.4**: GET /api/fee-config
- **REQ-INIT-001.5**: GET /api/admin/reconcile/config

All requests return ...[truncated]