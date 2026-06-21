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
WS 推 {channel: "system_update", type: "trading_day_changed", trd_date: today}
```

### REQ-INIT-004: 三屏障与日初的依赖

未做日初 → `/api/orders/place` 返 503 `RECONCILE_NOT_DONE`
（见 `trading/spec.md` REQ-TRADE-005 三屏障）

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
