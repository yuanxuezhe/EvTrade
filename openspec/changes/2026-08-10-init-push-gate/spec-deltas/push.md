# spec-delta: push — init_start / init_aborted 广播

## REQ-PUSH-043（新增）：init 生命周期广播 init_start / init_aborted（init-push-gate 2026-08-10）

后端 `init_trading_day`（`server/api/admin/sys_status.py`）MUST 在 init 生命周期关键点广播 `system_status_change`（复用 `system_update` 频道）：

- **init_start**：`do_reconcile(reconcile_kind='init')` **调用前**广播，`status='initializing'`，`change_kind='init_start'` — 前端据此开推送丢弃门
- **init_aborted**：reconcile 失败分支 MUST 广播，`status='error'`，`change_kind='init_aborted'`（原失败路径无广播，若缺失前端门会死锁）
- **init_completed**：既有成功广播保留（`status='ok'/'partial'`，`change_kind='init_completed'`）— 前端据此关门 + resetForNewDay

统一承载字段：`{ type:'system_status_change', change_kind, trd_date, previous_trd_date, status, report_id, ts }`。

**不在范围**：不写 `sys_status.status` 为 'initializing'（trade/day-init 守门依赖 status='active'）。

#### Scenario: 日初开始先广播 init_start

- **WHEN** admin POST /api/admin/sys-status/init
- **THEN** 在 `do_reconcile` 执行前 MUST 广播 `change_kind='init_start'`, `status='initializing'`
- **AND** 前端收到后开丢弃门

#### Scenario: 日初失败补广播 init_aborted

- **WHEN** `do_reconcile` 失败（result.ok=False）
- **THEN** MUST 广播 `change_kind='init_aborted'`, `status='error'`
- **AND** 前端收到后关丢弃门（不 resetForNewDay）

#### Scenario: 日初成功关门前先广播 init_completed

- **WHEN** `do_reconcile` 成功
- **THEN** MUST 广播 `change_kind='init_completed'`（既有行为）
- **AND** 前端收到后关丢弃门 + resetForNewDay

## Cross References

- `push/spec.md` REQ-PUSH-041（system_update 频道）/ REQ-PUSH-006（init_completed 触发刷新）
- `frontend/spec.md` REQ-FE-532（initializing 推送丢弃门）
