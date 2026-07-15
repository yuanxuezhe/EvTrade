# system-init — 系统初始化与管理员控制

> 本 spec 从 `changes/archive/2026-06-15-fix-system-init-and-users-api/spec-deltas/system-init.md` 上升而来（v6 实施 commit 已落地）。

## 范围

管理员在交易日开始前通过 SystemInit 页面完成：日初对账、激活交易日、查看历史 90 天交易状态、会话窗口、对账配置、费率配置。

## 端点契约

### REQ-INIT-001: SystemInit Page Data Loading

The SystemInit page **MUST** load all status data on mount via 3 parallel requests:

- **REQ-INIT-001.1**: GET `/api/admin/trading-day/active`
  - 返 `TradingDayOut | null`：当前激活交易日；`null` = 未做日初
- **REQ-INIT-001.2**: GET `/api/admin/trading-day?days=90`
  - 返 `List[TradingDayOut]`：历史 90 天交易日
- **REQ-INIT-001.3**: GET `/api/admin/trading-session`
  - 返 `TradingSessionOut`：当前会话（连续竞价 / 集合竞价 / 休市）
- **REQ-INIT-001.4**: GET `/api/fee-config`
  - 返 `FeeConfigOut`：当前费率配置（佣金/印花税/过户费）
- **REQ-INIT-001.5**: GET `/api/admin/reconcile/config`
  - 返 `ReconcileConfigOut`：对账配置（自动/手动模式、阈值）

所有请求返 `{code, msg, list}` 统一格式（code=0 成功）；前端 axios 拦截器自动展平。

## 角色守卫

### REQ-INIT-002: 管理员独占

所有 `/api/admin/*` 端点 **MUST** 由 `Role=admin` 用户访问；trader 角色访问返 403。

JWT payload 含 `role` 字段，由 `server/auth/dependencies.py:require_admin` 守卫。

## 数据流

### REQ-INIT-003: 日初对账流程（Active Trading Day 切换）

```
Admin 点击"激活今日"
  ↓
POST /api/admin/trading-day/init
  ↓
do_reconcile(trd_date=today)
  ├─ qry_orders (RPC) → 落 orders 表
  ├─ qry_trades (RPC) → 落 trades 表
  ├─ qry_positions (RPC) → 落 positions 表
  ├─ qry_asset (RPC) → 落 assets 表
  └─ 写 reconcile_report (mode=init, status=success/fail)
  ↓
UPDATE sys_status SET trd_date=today, last_reconcile_at=now
  ↓
WS 推 {channel: "system_update", type: "init_completed", trd_date: today, report_id, status}
```

### REQ-INIT-003.1: 日初成功后 ws 推 init_completed

- **WHEN** `POST /api/admin/sys-status/init` 成功（`result.ok=True` 且 `rpc_status != 'failed'`，即 `'ok'` 或 `'partial'`）
- **THEN** 后端通过 `ws_manager.broadcast('system_update', ...)` 推送 1 帧：
  ```json
  {
    "type": "init_completed",
    "trd_date": "20260715",
    "report_id": 123,
    "status": "ok" | "partial",
    "ts": "2026-07-15T15:30:00"
  }
  ```
- **AND** 不阻塞 HTTP 响应（`asyncio.ensure_future` 调度，与 `services/push/dispatcher.py::_broadcast_trade_cfm` 范式一致）
- **AND** `status` 字段语义：`'ok'` = 全部 RPC 成功；`'partial'` = 部分 RPC 失败但交易日仍切成功
- **AND** 失败通道：`rpc_status='failed'`（全部 RPC 失败）→ **不**推送，前端 AppHeader 刷新按钮兜底
- **AND** `reconcile_only` 端点 (`POST /api/admin/sys-status/reconcile`) **不**推送（仅生成报告不切日，详见 REQ-INIT-005）

#### Scenario: 全成功

- **WHEN** `do_reconcile` 返回 `ok=True, applied=True, error=None`
- **THEN** 推 `status='ok'`，所有持仓/资金数据已落 DB

#### Scenario: 部分 RPC 失败但交易日切成功

- **WHEN** `do_reconcile` 返回 `ok=True, applied=True, error='qry_positions: timeout'`（positions 拉取失败但 asset 成功）
- **THEN** 仍推 `status='partial'`，前端刷新但持仓数可能缺失

#### Scenario: 全部 RPC 失败

- **WHEN** `do_reconcile` 返回 `ok=False, error='全部 RPC 失败: ...'`
- **THEN** **不**推送，前端 AppHeader 按钮兜底

#### Scenario: 仅生成对账报告（manual mode）

- **WHEN** `POST /api/admin/sys-status/reconcile` 调用
- **THEN** **不**推送（持仓无变化）

### REQ-INIT-004: 三屏障与日初的依赖

未做日初 → `/api/orders/place` 返 503 `RECONCILE_NOT_DONE`
（见 `trading/spec.md` REQ-TRADE-005 三屏障）

### REQ-INIT-005: reconcile_only 不推送

- **WHEN** `POST /api/admin/sys-status/reconcile` 端点（仅 manual 模式生成报告）
- **THEN** **不**推送 init_completed（持仓无变化，无需刷新）
- **AND** 仅刷新 SystemInit 页内的 `loadReports()`，不通知其他 tab

#### Scenario: reconcile_only 仅写报告

- **WHEN** admin 调 reconcile_only (`mode='manual'`)
- **THEN** do_reconcile 写 report 但不切交易日
- **AND** ws 不推送 init_completed
- **AND** SystemInit 页 loadReports() 刷新历史报告列表

## 影响 cap

- `trading/spec.md` REQ-TRADE-005 引用 REQ-INIT-003 日初屏障
- `push/spec.md` 引用 REQ-INIT-003 qry_* RPC 调用
- `configuration/spec.md` REQ-CFG-002 引用 REQ-INIT-001.4 费率配置
- `data-model/spec.md` 引用 `sys_status` / `trading_session` / `reconcile_config` / `reconcile_report` 表

## 关联文件

- 后端：`server/api/system_init.py` / `server/api/fee_config.py` / `server/api/admin.py` / `server/services/reconcile.py`
- 前端：`client/src/views/SystemInit.vue` / `client/src/api/system_init.js` / `client/src/stores/system_init.js`
- DB：`server/models/orm.py`（`SysStatus` / `TradingSession` / `ReconcileConfig` / `ReconcileReport`）
- 路由：FastAPI `/api/admin/*` 前缀，admin 角色守卫

## 测试

- `pytest server/test_admin.py` — admin 端点鉴权
- `pytest server/test_reconcile.py` — 日初对账流程
- `pytest server/test_fee_config.py` — 费率 CRUD


## Requirements

### Requirement: day-init reconcile 全表覆盖语义（v12 强化）

`do_reconcile` MUST 把 `positions` / `assets` 表**全表覆盖**为 broker 端权威数据。manual adjust 值在 reconcile 后会被全表覆盖抹掉 —— 这是预期的、不持久化的语义。

#### Scenario: reconcile 覆盖 manual adjust

- **WHEN** admin 上午 10:00 调平 `Position.vol += 100`（broker 期权行权但 trd_cfm 未来得及推）
- **AND** admin 下午 14:00 触发手动 `do_reconcile`（极端场景）
- **THEN** `Position.vol` 被 broker 真实值覆盖，100 delta 丢失
- **AND** UI 提示 admin"reconcile 已执行，原 manual adjust 已按柜台数据全表覆盖"

#### Scenario: 调平不影响 sys_status

- **WHEN** admin 调平 `Position.vol += 100`
- **THEN** `sys_status` 表不变（active 状态不受影响）
- **AND** `reconcile_report` 表不写（用户明确不留 audit row）

### Requirement: reconcile 不会自动叠加 manual adjust（v12）

`do_reconcile` MUST NOT 把 manual adjust 值叠加到 broker 全量结果之上。manual adjust 是 reconcile 之间的临时补丁。

#### Scenario: reconcile 清零 manual 标记

- **WHEN** `do_reconcile` 执行
- **THEN** `Position.synced_from = "rpc_full"`（覆盖原 `"manual"`）
- **AND** `Asset.synced_from = "rpc_full"`

#### Scenario: UI reconcile 后允许再次手动调平

- **WHEN** reconcile 后 broker 仍未对账的偏差仍存在
- **THEN** admin 可以再次调平
- **AND** 再次调平后 `synced_from = "manual"` 取代 `"rpc_full"`
- **AND** 下次 reconcile 又会被覆盖 — 形成自然循环
