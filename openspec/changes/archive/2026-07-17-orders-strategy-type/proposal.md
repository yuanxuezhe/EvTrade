# Proposal: orders.strategy_type — 策略类型字段

**Change ID**: `2026-07-17-orders-strategy-type`
**Status**: implemented
**Author**: Hermes Auto
**Date**: 2026-07-17

## Why

交易下单需要区分下单来源：
- **普通单 (Trade.vue OrderForm 下单)** — 用户日常手动下单，与做T无关
- **快速做T单 (T0Trade.vue 智能做T下单)** — 关联 t0_tasks 的做T流程单

当前只能通过 `user_def='T0'` 字段过滤做T单，但 `user_def` 是业务自由字段（前端可随意填），不可靠。需要一个**强约束的策略类型字段**支持：

1. **缓存快速过滤**：T0Trade 委托明细根据 `strategy_type=1` 过滤当前 task 的单（不再依赖 user_def 字符串匹配）
2. **数据维度聚合**：未来报表可按策略类型统计（普通单 vs 做T单的胜率/盈亏分布）
3. **撤单行继承原单 strategy_type**：cancel-row ORM 不显式设，自动 = 原委托值（保留分类语义）

## What

`orders` 表新增 `strategy_type` 列 + 索引，全链路透传：

### DB schema
- `orders.strategy_type: TINYINT NOT NULL DEFAULT 0`
  - `0` = 普通单 (Trade.vue OrderForm 下单)
  - `1` = 快速做T (T0Trade.vue 智能做T下单)
- `ix_orders_strategy_type(strategy_type)` 索引 — 缓存过滤 + 策略维度聚合
- 历史数据不回填（与 v18 task_id 同策略：`user_def='T0'` 单保持 `strategy_type=0`）

### API
- `PlaceOrderRequest.strategy_type: Literal[0, 1] = 0` — Pydantic 强约束
- `OrderOut.strategy_type: int = 0` — 输出 schema
- `_to_order_out(o)` 透传 + 兜底 0
- `_order_to_out_dict(order)` WS push dict 加 strategy_type + 兜底 0
- `place.py` ORM 构造加 `strategy_type=req.strategy_type`

### Frontend
- `Trade.vue` 普通单：handleOrderSubmit 注入 `strategy_type: 0`
- `T0Trade.vue` 快速做T：`_submitOrder` payload 加 `strategy_type: 1`
- `orderCalc.js metaMerge` 透传 strategy_type（与 task_id 同模式，防缓存 filter 失效）
- `CacheOrders.vue` 加 strategy_type 列
- `TodayOrdersPanel.vue` 加"策略"chip 列：1 → 红色"做T"，0/缺失 → "普通"

## How

### 4-commit 拆分（跨层独立可 revert）

1. `feat(db)` `4f23ae7` — migration 脚本 + ORM 加 strategy_type 列 + 索引
2. `feat(api)` `894379e` — schemas (PlaceOrderRequest/OrderOut Literal) + place ORM 写入 + helpers WS push 透传
3. `feat(ui)` `55cbcb4` — Trade.vue/T0Trade.vue 下单注入 + orderCalc.js metaMerge 透传 + CacheOrders.vue 列 + TodayOrdersPanel.vue chip
4. `docs(spec)` 待 commit — 本 changeset + spec delta

### OpenSpec 增量
- `specs/data-model/spec.md` §1 orders 表加 strategy_type 行
- `specs/intraday-orders-trades-cache/spec.md` 加 REQ-CACHE-STRA-001/002（缓存 schema 透传 + UI 列展示）
- `specs/trading/spec.md` 加 REQ-TRADE-026（下单 strategy_type 业务契约）

### Migration 幂等性
- 探测 `INFORMATION_SCHEMA.COLUMNS` 跳过重复 ALTER
- 探测 `INFORMATION_SCHEMA.STATISTICS` 跳过重复 CREATE INDEX
- MySQL 8 不支持 `CREATE INDEX IF NOT EXISTS`，但 inspect() 探测后跳过即可

### 验证清单
- [x] Migration 幂等（第二次跑全 SKIP）
- [x] `_to_order_out` 透传 strategy_type（ORM 实测）
- [x] `_order_to_out_dict` WS push 透传（ORM 实测）
- [x] Pydantic Literal 拒绝 `strategy_type=2`
- [x] 后端实测 ORM 写入 strategy_type=1 成功

### 浏览器实测（下一步）
- [ ] Trade.vue 下单 → 缓存 strategy_type=0
- [ ] T0Trade.vue 下单 → 缓存 strategy_type=1
- [ ] TodayOrdersPanel "策略"列显示正确 chip

### 后续候选（不在本 PR）
- T0Trade.vue 委托明细 filter 改 `o.strategy_type === 1`（权威字段，目前仍用 user_def）
- metaMerge 自动化测试（v65 补过 task_id 单测可借鉴）
