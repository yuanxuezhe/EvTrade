# Tasks: Fix SystemInit & Users API Contract Bugs

## Phase 1: Backend (5 bug)

- [ ] T1.1 server/api/admin/trading_day.py: 删 do_reconcile 的 mode kwarg
  (do_reconcile 不支持 mode 参数, 传 mode=req.mode 会 TypeError)
- [ ] T1.2 server/api/admin/trading_day.py: TradingDayOut 字段直接命名
  (去掉 alias 改 populate_by_name; 字段直接是 trd_date/activated_at/activated_by)
- [x] T1.3 server/api/fee_config.py: stamp_tax_rate 默认 0.0005 → 0.001 (A 股实...[truncated]