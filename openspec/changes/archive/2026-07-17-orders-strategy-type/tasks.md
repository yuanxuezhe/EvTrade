# Tasks: orders.strategy_type

> 实施 checklist — 配合 proposal.md 的 4-commit 拆分。

## Stage 1: 探索 + 拍板 [done]
- [x] 探索后端 ORM (`server/models/orm.py::Order`) + schema (`server/api/orders/schemas.py`) + place.py + helpers.py + migration 参考 (`2026-07-08-add-t0-tasks.py`)
- [x] 探索前端 `OrderForm.vue`/`Trade.vue`/`T0Trade.vue`/`orderCalc.js`/`CacheOrders.vue`/`TodayOrdersPanel.vue`
- [x] 探索 OpenSpec 现有 REQ-TRADE-013 (v18 task_id 模式) + data-model §13 task_id
- [x] 出方案 A/B/C + Q1-Q5 拍板清单 → 用户答"全按默认"

## Stage 2: 工件 [done]
- [x] `openspec/changes/2026-07-17-orders-strategy-type/proposal.md` (3773 bytes)
- [x] `openspec/changes/2026-07-17-orders-strategy-type/spec-deltas/data-model.md` (REQ §14)
- [x] `openspec/changes/2026-07-17-orders-strategy-type/spec-deltas/trading.md` (REQ-TRADE-026)
- [x] `openspec/changes/2026-07-17-orders-strategy-type/spec-deltas/frontend.md` (REQ-FE-530)
- [x] `openspec/changes/2026-07-17-orders-strategy-type/tasks.md` (本文档)

## Stage 3: 实施

### commit.1: DB 层 (db migration + ORM)
- [x] 写 `server/migrations/2026-07-17-add-orders-strategy-type.py` (4922 bytes, 幂等 ALTER + CREATE INDEX, INFORMATION_SCHEMA 探测)
- [x] `server/models/orm.py` Order 加 `strategy_type` Column (Integer, NOT NULL, default=0)
- [x] `server/models/orm.py` Order `__table_args__` 加 `Index("ix_orders_strategy_type", "strategy_type")`
- [x] `server/models/orm.py` Order docstring 加 v66 schema 改动说明
- [x] **commit `4f23ae7`** `feat(db): orders 表加 strategy_type 字段 + ix_orders_strategy_type 索引 (REQ-TRADE-026)`

### commit.2: API 层 (schemas + place + helpers)
- [x] `server/api/orders/schemas.py` import 加 `Literal`
- [x] `server/api/orders/schemas.py` PlaceOrderRequest 加 `strategy_type: Literal[0, 1] = 0`
- [x] `server/api/orders/schemas.py` OrderOut 加 `strategy_type: int = 0`
- [x] `server/api/orders/schemas.py` `_to_order_out` 加 strategy_type 透传 + 兜底 0
- [x] `server/api/orders/place.py` ORM 构造加 `strategy_type=req.strategy_type`
- [x] `server/services/push/helpers.py` `_order_to_out_dict` 加 strategy_type + 兜底 0
- [x] **commit `894379e`** `feat(api): strategy_type 全链路透传 (place → ORM → WS push) (REQ-TRADE-026)`

### commit.3: 前端层 (Trade.vue + T0Trade.vue + orderCalc.js + CacheOrders.vue + TodayOrdersPanel.vue)
- [x] `client/src/views/Trade.vue` `handleOrderSubmit` 注入 `strategy_type: 0`
- [x] `client/src/views/T0Trade.vue` `_submitOrder` payload 加 `strategy_type: 1`
- [x] `client/src/utils/orderCalc.js` metaMerge 透传 strategy_type (与 task_id 同模式)
- [x] `client/src/utils/orderCalc.js` docstring 加 v66 说明
- [x] `client/src/views/CacheOrders.vue` fields 加 strategy_type 列
- [x] `client/src/components/trade/TodayOrdersPanel.vue` 加 "策略" chip 列
- [x] **commit `55cbcb4`** `feat(ui): strategy_type 前端透传 + 缓存展示 + T0 下单标记 1 (REQ-TRADE-026)`

## Stage 4: 验证

### DB 验证 (backend 跑 v66 commit 后)
- [x] migration 跑两次都 OK (第二次全 SKIP, 幂等)
- [x] `SHOW COLUMNS FROM orders LIKE 'strategy_type'` → `tinyint NO MUL 0`
- [x] `SHOW INDEX FROM orders WHERE Key_name='ix_orders_strategy_type'` → BTREE

### API 验证 (Pydantic + ORM 实测)
- [x] PlaceOrderRequest `strategy_type=2` → 422 ValidationError (Literal 约束)
- [x] PlaceOrderRequest 默认 `strategy_type=0`
- [x] `_to_order_out` 实测 ORM 行 strategy_type=1 透传正确
- [x] `_order_to_out_dict` 实测 strategy_type=1 透传正确
- [x] ORM 直接 INSERT strategy_type=1 单成功 (新 order_no 落库)

### 后端实测 (curl POST + WS push)
- [x] 重启 backend (PID 3497471, port 8000, /api/health OK)
- [x] curl POST `/api/orders/place` strategy_type=0 → ORM 落库 strategy_type=0 (RPC 慢路径超时, 但 ORM 已写入)
- [ ] 浏览器实测 Trade.vue 下单 → 缓存 strategy_type=0
- [ ] 浏览器实测 T0Trade.vue 下单 → 缓存 strategy_type=1
- [ ] 浏览器实测 TodayOrdersPanel "策略" chip 显示正确

## Stage 5: 同步主 spec (apply step 5.5)
- [x] `openspec/specs/data-model/spec.md` §13 之后加 `### Requirement: 14. orders.strategy_type 列新增` (v66 NEW) — 见 spec-deltas/data-model.md
- [x] `openspec/specs/trading/spec.md` 加 `### REQ-TRADE-026` (5 scenario) — 见 spec-deltas/trading.md
- [x] `openspec/specs/frontend/spec.md` 加 `### REQ-FE-530` (4 scenario) — 见 spec-deltas/frontend.md

## Stage 6: 归档 (commit.4)
- [x] 合并 spec-deltas 到 `specs/{data-model,trading,frontend}/spec.md`
- [ ] `git add openspec/` 全部 + `git commit` "docs(spec): REQ-TRADE-026 + REQ-FE-530 strategy_type 契约"
- [ ] `git mv openspec/changes/2026-07-17-orders-strategy-type openspec/changes/archive/`
- [ ] `git push origin master --force-with-lease` (force-with-lease 因远端可能有人推过; 默认 safe)

## Stage 7: 后续候选 (v67+)
- [ ] T0Trade.vue 委托明细 filter 改 `o.strategy_type === 1` (权威字段, 替代 user_def 字符串匹配)
- [ ] metaMerge 自动化单测 (v65 补 task_id 单测, v66 同样需要)
- [ ] 缓存查 task_id + strategy_type 联合索引 (如报表需求确认)
