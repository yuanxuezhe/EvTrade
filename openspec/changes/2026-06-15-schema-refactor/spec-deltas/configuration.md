# configuration spec delta

## 新增 REQ-CFG-006: 系统状态机（v5 schema refactor）

- 表名：`trading_day` → **`sys_status`**
- 类名：`TradingDay` → **`SysStatus`**
- 主键：`id`（自增）→ **`trd_date`**（YYYYMMDD）
- `current_date` 字段重命名为 **`trd_date`**
- 状态字段：`status` ∈ {`pending`, `active`, `closed`}
- 其他字段：`is_half_day` / `initialized_at` / `initialized_by` / `closed_at` / `closed_by` / `remark` / `created_at`
- URL：`/api/admin/trading-day*` → **`/api/admin/sys-status*`**
- Pydantic：`TradingDayOut` → **`SysStatusOut`**，字段 `current_date` → **`trd_date`**

## reconcile_config / reconcile_report 字段

- `reconcile_config`：单行表（`id=1` CheckConstraint 保留），无字段变化
- `reconcile_report`：
  - `TRD_DATE` → `trd_date`（小写）
  - 主键：`id`（自增）→ **复合 `(trd_date, mode, created_at)`**
  - 报告详情接口：`GET /api/admin/reconcile/reports/{trd_date}/{mode}/{created_at}`
  - 列表响应不再用 `id`，改用 `created_at` 时间戳作为前端 key
