# data-model delta — v13 orders.raw_id 列（user_def 语义保持不变）

> change `layered-architecture-and-strategy-master` — 补集增量
>
> **本 delta 不创建 strategy 主表**（远程 change `2026-07-05-strategy_trade` 已实现，含 4 张表 `Strategy` / `StrategyRegime` / `StrategyGrid` / `StrategyAudit`，详见 `openspec/specs/strategy/spec.md`）。本 delta 仅追加 `orders.raw_id` 列。

## MODIFIED Requirements

### §1 orders 表

#### Schema 变更
- **新增字段**：`raw_id`（`String(8)`，nullable，**无 default**）
- **`user_def` 字段不动**（远程 `2026-07-05-strategy_trade` 之后 `user_def` 三种取值并存）：
  - 普通 strategy 委托：`str(strategy.id)`（远程 REQ-TRADE-011 约定）
  - 手动 T0 委托：`"T0"`（历史）
  - 撤单审计行：`f"CANCEL:{orig_order_no}"`（v9 约定，不动）

#### 新字段表（差量）

| 字段 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| `raw_id` | String(8) | YES | NULL | **v13 NEW**：被撤/被引用委托的本地 order_no；DELETE 端点 INSERT cancel-row 时写入 = 原委托 order_no；非 cancel-row 为 NULL；旧数据全 NULL |

#### 业务规则新增（v13 段）

- **`raw_id` 写入点**：仅 DELETE 端点 INSERT cancel-row 时写入（`raw_id = orig.order_no`）；place 端点 INSERT 普通行时 `raw_id = NULL`；broker `ord_cfm` 不写 `raw_id`（broker 不知道这个本地概念）
- **`raw_id` 与 `order_id` 区别**：`order_id = broker 真实柜台号`（ord_cfm 到达时写入）；`raw_id = 本地 order_no`（cancel-row 指向父单）；两者语义完全不同，命名刻意区分避免歧义
- **`raw_id` 与 `user_def` 关系**：cancel-row 写入后**两者并存**：
  - `user_def = f"CANCEL:{orig_order_no}"`（v9 约定，用于交易审计筛选）
  - `raw_id = orig.order_no`（v13 新增，用于结构化关联，避免 user_def 字符串解析）
  - 两者表达同一关联（cancel-row → 父委托），但 `raw_id` 是结构化字段，前端 query / JOIN 友好
- **冗余可接受**：`user_def` 保留向后兼容（远程 v9 audit 数据无破坏），`raw_id` 是 v13 起的结构化推荐字段；未来如彻底迁移到 `raw_id`，可走独立的 deprecation 流程

#### 唯一索引/普通索引

- **不新增** `raw_id` 索引（cancel-row query 走 `WHERE trd_date=? AND order_no=?` 已有 PK 覆盖；`raw_id` 单列查询少）
- 不动 `ix_orders_user_def`（远程 `2026-07-05-strategy_trade` 已加）

## ADDED Requirements

（本段保留空 — 远程 `2026-07-05-strategy_trade` 已实现 strategy 主表，本 change 不再新增）

## Migration

- 迁移脚本：`server/migrations/2026-07-06-add-orders-raw-id.py`
  - idempotent `ALTER TABLE orders ADD COLUMN raw_id VARCHAR(8)`
  - 列存在则 skip（`PRAGMA table_info(orders)` 检测）
  - 不强制回填（旧数据 raw_id 全 NULL，无需回填）
- 新部署：`infra.db.init_db()` 自动建（远程 strategy_trade 已注册 strategy 模型；本 change 不新增 model）

## 跨表引用（v13 新增）

- `orders.raw_id → orders.order_no`（逻辑 FK，cancel-row 指向父单；不新增物理 FK 约束）
- 不影响 `orders.user_def → strategy.id`（远程 REQ-TRADE-011 约定，逻辑 FK）
- 两条逻辑 FK 走各自的索引（`ix_orders_user_def` 远程 + 不索引 raw_id）

## 单行表统计

总表数保持 11 + 4 = 15 张（远程 strategy_trade 新增 4 张 strategy 相关表；本 change 不新增表）。