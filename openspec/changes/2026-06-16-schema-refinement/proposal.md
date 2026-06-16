# Schema refinement v7 — Order 去掉 order_id 关联约束 + Trade 改用 order_no

## Why

刚创建 `data-model/spec.md` 知识库后，复查 schema 发现 3 处设计缺陷：

### 缺陷 1：Order 主键虽然已经不是 `order_id`，但仍有两个 UNIQUE 约束关联 `order_id`

- `uq_orders_broker_id(order_id, trd_date)` — broker 真实号定位
- `ix_orders_order_id(order_id)` — trd_cfm 兜底

**问题**：下单时 `order_id` 为空（broker 还没回执），UNIQUE(order_id, trd_date) 在空值场景下行为不稳定（SQLite 把多个 NULL 视为不等，多个空 order_id 不会冲突，但 MySQL 行为不同），业务语义含糊。

`ix_orders_order_id` 是普通 INDEX 而非 UNIQUE，没有这个问题，但应该明确这是**兜底查询索引**，不是约束。

### 缺陷 2：`client_order_id` 字段不该存在

- 当前 `client_order_id` 是 `nullable=False`，且有 `uq_orders_client_trd(client_order_id, trd_date)` UNIQUE 约束
- 但幂等的正确实现是：客户端生成 cid → 调 `ord_stk` RPC（broker 端透传到 remark） → broker 端拒重复 remark
- 根本不需要 DB 层 UNIQUE 约束；UNIQUE(cid, trd_date) 让客户端必须每个请求都生成不一样的 cid，否则会被 DB 拒（应该是 broker 拒）

**替代**：
- 删 `client_order_id` 字段
- 加 `user_def: String(255)` 字段（外部自定义信息透传字段，默认空字符串，不做约束）
- 删 `uq_orders_client_trd` 约束

### 缺陷 3：Trade 表用 `order_id` 关联 Order 不稳定

- `Trade.order_id` 是 broker 真实号
- `Trade` PK = `(trd_date, trade_id)` 只保证成交自身唯一
- 但 trd_cfm（成交回报）通常**早于** ord_cfm（委托确认）到达 — broker 先成交、再委托确认
- 用 broker `order_id` 关联会让 trd_cfm 在 ord_cfm 到达前无法稳定关联到本地 Order
- `order_no` 在 ord_stk 下单时就已生成，是稳定的本地关联键

**替代**：
- Trade PK = `(trd_date, order_no, trade_id)`（**order_no 入 PK**，同委托下成交唯一）
- 删 `Trade.order_id` 字段
- `ix_trades_order(order_id)` → `ix_trades_order_no(order_no)`（重命名）

## What Changes

### 1. `server/models/orm.py` — Order

- 删除字段：`client_order_id`
- 新增字段：`user_def = Column(String(255), nullable=False, default="")`
- 删除约束：`UniqueConstraint("client_order_id", "trd_date", name="uq_orders_client_trd")`
- 删除约束：`UniqueConstraint("order_id", "trd_date", name="uq_orders_broker_id")`

### 2. `server/models/orm.py` — Trade

- 删除字段：`order_id`
- 新增字段：`order_no = Column(String(8), primary_key=True, nullable=False)`（入 PK）
- PK 改为 `(trd_date, order_no, trade_id)`
- Index 重命名：`ix_trades_order(order_id)` → `ix_trades_order_no(order_no)`

### 3. `server/api/orders.py` — PlaceOrderRequest / OrderOut / place_order 流程

- `PlaceOrderRequest` 字段：
  - 删除 `client_order_id: str`
  - 新增 `user_def: str = ""`
- `place_order` 幂等：
  - **不再**用 `db.query(Order).filter_by(client_order_id=cid, trd_date=...)` 查重
  - 改成：直接 `next_order_no(db)` → 落表（应用层顺序保证，不重复）
  - 真正的"幂等"靠 broker 端（重复 `remark`/`order_no` 被拒）
- `OrderOut` schema：
  - 删除 `client_order_id` 字段
  - 新增 `user_def: str` 字段
  - `order_id` 保持可空（None → 字符串 `""`）

### 4. `server/services/push_handlers.py:handle_trd_cfm`

- 解析 `remark` → `order_no`（已有逻辑）
- 落 `Trade` 时**不再写** `order_id`，写 `order_no`（PK 第二段）
- 若 `order_no` 解析失败 → 打 warning + 跳过该条成交（**不写一条孤儿 Trade**）

### 5. `server/services/push_handlers.py:handle_ord_cfm`

- `Order.order_id` 写入保持不变（broker 真实号首次到达时写入）

### 6. 测试套件同步

- `server/test_push_handlers.py`：Trade 构造去掉 `order_id`，加 `order_no`
- `server/test_models.py`（如有）：Trade 字段调整
- `server/test_orders_api.py`（如有）：PlaceOrderRequest 字段调整；幂等测试改用 user_def

### 7. spec 同步

- `data-model/spec.md`：§1 orders 表 + §2 trades 表 已改
- `trading/spec.md` REQ-TRADE-002：v7 schema 调整说明
- `push/spec.md` REQ-PUSH-001：v7 落库调整说明

## Capabilities

### Modified Capabilities
- `data-model`: 11 张表结构 v7 修订
- `trading`: 下单幂等契约
- `push`: trd_cfm 落库

## Impact

- `server/models/orm.py` — Order + Trade 重构
- `server/api/orders.py` — `PlaceOrderRequest` / `OrderOut` / `place_order` 流程
- `server/services/push_handlers.py` — `handle_trd_cfm` 字段调整
- `server/test_*.py` — 测试构造更新
- 前端无改动（前端已用 `user_def` 概念叫 `remark` 字段；本轮后端字段调整是 `user_def` 透传，前端可能需要后续调用 `place_order` 时把 `remark` 改名为 `user_def` —— 留作下轮）
- ⚠️ **DB 重置**：dev 期需 `rm server/evtrade.db`（schema 变更）

## Verification

1. `rm server/evtrade.db && python -c "from db import init_db; init_db()"` 重建表
2. `pytest server/ -v` 全绿（除 2 个已知 Python 3.6 asyncio 失败）
3. 手动：place_order → 收到 ord_cfm → 收到 trd_cfm → Trade 表 `order_no` 与 Order.order_no 一致
4. 手动：DELETE /api/orders/{order_no}?trd_date=... → 撤单成功
5. grep 自检：
   ```bash
   grep -rn "client_order_id" server/ client/src/ --include="*.py" --include="*.vue" --include="*.js"
   ```
   应只命中 archive/ 或本 spec。
   ```bash
   grep -rn "Trade.*order_id" server/ --include="*.py"
   ```
   应只命中 archive/ 或本 spec。

## BREAKING

- `Order` 删字段：`client_order_id` → 所有写 Order 的代码需移除该字段
- `Order` 删约束：`uq_orders_client_trd` / `uq_orders_broker_id` → 所有依赖此 UNIQUE 的幂等/查询逻辑改用 order_no / 普通索引
- `Trade` 删字段：`order_id` → 所有读 Trade.order_id 的代码需改读 order_no
- `Trade` PK 变化：`(trd_date, trade_id)` → `(trd_date, order_no, trade_id)` → 所有 Trade 写入需提供 order_no
- `PlaceOrderRequest` 字段重命名：`client_order_id` → `user_def`（语义放宽：纯透传，不参与幂等）

## Spec Deltas

见 `spec-deltas/data-model.md`、`spec-deltas/trading.md`、`spec-deltas/push.md`。
