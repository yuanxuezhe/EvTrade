# Tasks — 2026-06-15-schema-refactor

## 1. 数据层
- [x] 重写 `server/models/orm.py`（6 张业务表 + 5 张配置/单行表）
- [x] 重写 `server/models/types.py`（同步 dataclass）
- [x] 跑 `python -c "from models.orm import *"` 确认加载

## 2. Service 层
- [x] 改 `services/push_handlers.py`（4 个 handler + `_get_active_trd_date`）
- [x] 改 `services/reconcile.py`（`_apply_broker_data` / `do_reconcile`）
- [x] 改 `services/guards.py` + `trading_clock.py`（用 `SysStatus` + `trd_date`）
- [x] 改 `services/t0.py`（字段重命名）

## 3. API 层
- [x] 改 `api/orders.py`（Pydantic / 复合主键 / DELETE 加 `trd_date`）
- [x] 改 `api/trades.py` / `positions.py` / `holdings.py` / `asset.py` / `t0_stats.py`
- [x] 重命名 `api/admin/trading_day.py` → `sys_status.py`
- [x] 改 `api/admin/__init__.py` 和 `api/admin/reconcile.py`

## 4. 路由注册
- [x] 改 `main.py`：URL → `/api/admin/sys-status`、tag → `admin-sys-status`

## 5. 测试
- [x] 改 `test_models.py`（11 张表 + 新 PK 约束）
- [x] 改 `test_push_handlers.py`（4 类 push + `remark` 匹配）
- [x] 改 `test_orders_api.py`（idempotent / barrier / cancel / trd_date）
- [x] 改 `test_reconcile.py`（URL 改 + 字段改）
- [x] 改 `test_guards.py`（`SysStatus` / `trd_date`）
- [x] 改 `test_holdings_api.py`（6 字段格式 / `last_vol` / `avl_vol` / `vol` / `cost_price`）

## 6. 前端
- [x] 改 `api/admin.js`（`sysStatusApi` + URL 路径）
- [x] 改 `stores/ws.js`（`remark` 字段 + 去 `order_remark`）
- [x] 改 `stores/holdings.js`（`cost` → `cost_price` + `vol`）
- [x] 改 `components/PositionTable.vue` / `PositionDetail.vue`
- [x] 改 `views/Holdings.vue` / `Position.vue` / `Dashboard.vue` / `Orders.vue` / `Trade.vue` / `T0Trade.vue`
- [x] 改 `views/SystemInit.vue`（`sysStatusApi`）
- [x] 改 `composables/useT0Balance.js`（`cost_price` / `avl_vol` / `vol`）

## 7. OpenSpec
- [x] 更新 `specs/positioning/spec.md`（字段重命名）
- [x] 更新 `specs/trading/spec.md`（order_no / 复合主键 / DELETE 改）
- [x] 更新 `specs/push/spec.md`（push 结构 + `remark` 匹配规则）
- [x] 更新 `specs/configuration/spec.md`（新增 REQ-CFG-006 `sys_status`）
- [x] 新建 `changes/2026-06-15-schema-refactor/{proposal.md, tasks.md, spec-deltas/*}`

## 8. 验证
- [ ] 跑 `pytest server/ -v` 全绿（环境需 Python 3.8+，3.6 下 `AsyncMock` 不可用）
- [ ] 全文 `grep` 确认无 `TRD_DATE` / `order_remark` / `current_date` / `initial_position` 残留
- [ ] 手动跑通下单 → 推送 → 状态更新流程
