# Layered Architecture + orders.raw_id — 服务端分层重构 + 撤单结构化字段（strategy 部分已被远程覆盖）

> MED 级 / L 工作量。**三大主题捆绑**（scope 较 v13 初版缩小）：
> ①后端按"基础设施层 / 仓库层 / RPC 层 / 服务端接口层 / 业务编排层"显式分层（与远程 `2026-07-05-strategy_trade` 横向正交，不冲突）；
> ②新增 `orders.raw_id` 列作为 cancel-row 的结构化冗余字段（user_def 语义保持远程 REQ-TRADE-011 不变）；
> ③测试目录按层镜像（继续 `2026-07-02-restructure-test-layout` 未完成的部分）。
>
> **本 change 不实现 strategy 主表 / 不改 strategy_type / 不改 user_def 写入规则** — 远程 `2026-07-05-strategy_trade` 已实现（含 4 张表 + StrategyTrade.vue 完整前端 + REQ-TRADE-011 user_def 关联约定），本 change 在 spec 层面承认其存在并避免 schema 冲突。
>
> **核心约束**：本次重构**不修改任何已有代码逻辑** — 所有变更要么是文件搬迁（import 路径调整），要么是加性增强（新可选列，默认值 NULL 兼容现有调用），要么是基类抽象（外部接口完全保持）。

## 1. Why

### 1.1 现状问题

**架构层面：**
- `server/services/` 当前混杂两类职责：①"按表聚合的 CRUD"（`order_no.py` `order_status.py` `trading_clock.py`），②"跨表业务编排"（`t0/` `push/` `reconcile.py` `strategy/`）。前者跟"业务"无关，本质是数据库基类的封装；后者跟"数据库"无关，是 RPC + DB 的复合编排。
- `server/rpc/transport.py:RPClient` 已经承担"RMQ 长连接基类"职责，但**命名空间**不叫 `infra/`，未来加第二条 RMQ 业务线会复制粘贴。
- `server/db.py` 的 `Base / SessionLocal / get_db / db_session` 没有"基类"的概念，散在根目录，未来加读写分离 / 分库分表没有挂载点。
- 21 个 `server/test_*.py` 散在 `server/` 根目录（远程 `2026-07-02-restructure-test-layout` 已迁部分到 `tests/server/`，但遗留 21 个未迁），跟正式代码混在一起 → 违背 CLAUDE.md「模块解耦」+ 用户原始需求 (f)。
- 远程 `2026-07-05-strategy_trade` 实施后 `server/services/strategy/` 内部未建 `__init__.py` 全符号 re-export，深层路径引入（如 `from server.services.strategy.indicators import ma`）普遍，违背未来 REQ-ARCH-004 — 后续应通过 `__init__.py` 收敛（不属本 change）

**业务层面：**
- 当前 DELETE 端点生成的 cancel-row 唯一指向父委托的字段是 `user_def="CANCEL:{orig_order_no}"`（v9 起），纯字符串。前端做 cancel-row 关联查询需解析字符串（`substr(user_def, 8)`），结构化不友好。
- 运营/审计侧希望 cancel-row 关联查询走结构化字段（`raw_id` 数字），但又不希望破坏 v9 audit 数据（`user_def` 保留向后兼容）。

### 1.2 用户原话

> a、工具基类：包含处理消息队列的基类、处理数据库的基类。
> b、RPC接口类：通过与消息队列交互，实现查询、下单等接口
> c、 数据库操作类，调用数据库基类，实现读写本地数据库的操作
> d、服务端接口类，结构供前端调用，如查询本地数据库信息接口、委托接口等，委托接口先写本地数据库，再调RPC接口发送。
> f、将项目test*相关的代码，都放到test对应目录，不要混在正式代码中。
>
> ——后续澄清：
> - CANCEL 如果向RPC撤子单，则新增一条orders记录，orders增加一列raw_id，存储被撤委托的order_no
>
> （本 change 不包含 e 全部 / 部分 strategy 主表相关需求 — 远程 `2026-07-05-strategy_trade` 已覆盖 strategy 主表，但 schema 选择不同 [int PK + VARCHAR(16) type enum]；如需 4 view 显式打标 0/1/2/3 可走 follow-up change）

### 1.3 关键架构约束

- **不改逻辑**：CLAUDE.md + 用户明确要求；所有现有 handler 的控制流、状态机、错误分支一律不动；只搬文件 + 加可空列 + 兼容垫片。
- **monkeypatch 路径稳定**：`test_orders_api.py` 走 `monkeypatch.setattr("server.api.orders.ord_stk", mock)` 路径，迁移后这个字符串必须仍可工作 → `server/api/orders/__init__.py` 顶层 re-export 不能改路径。远程 `2026-07-05-strategy_trade` 类似：测试用 `monkeypatch.setattr("server.api.strategy.X", mock)` 命中 `api/strategy.py` 顶层 re-export。
- **远程 strategy 不重写**：`server/services/strategy/` 远程 v1 实现含 models / repository / indicators / flags / regime / grid / engine / quote_consumer / audit 9 个子模块，本 change 不动；承认其作为 services 层成员，仅在 server-architecture spec 中明确"deep import 暂豁免"。
- **后端数据库是 SQLite + 手写 SQL 迁移**（项目历史约定：`server/migrations/` 目录）；不引入 Alembic。

## 2. What Changes

### 2.1 后端分层（5 件套目录结构）

```
server/
├── infra/           ★ NEW 基类层
│   ├── __init__.py
│   ├── mq.py        ← MessageQueueClient（aio_pika RMQ 长连接基类）
│   └── db.py        ← DatabaseBase / SessionLocal / Base / get_db / db_session
├── repo/            ★ NEW 仓库层（按表聚合的 CRUD）
│   ├── __init__.py
│   ├── orders.py    ← 含 _infer_order_status / next_order_no
│   ├── trades.py
│   ├── positions.py
│   ├── assets.py
│   ├── system.py    ← sys_status / trading_session / fee_config / reconcile_config
│   └── quote_snapshots.py
├── rpc/             ← 已存在，改为继承 infra.mq.MessageQueueClient
│   ├── transport.py   (RPClient 继承 MessageQueueClient)
│   ├── client.py      (facade)
│   ├── handlers.py
│   └── parsers_*.py
├── services/        ← 缩小到"跨表业务编排"（保留 t0/, push/, reconcile.py, guards.py, strategy/）
│                       ★ strategy/ 是远程 v1 实现，本 change 不动
├── api/             ← 不变（FastAPI 路由，含远程 strategy.py）
├── models/, ws/, enums/, auth/, middleware/, lifecycle/  ← 不变
├── tests/strategy/  ← 远程 v1 测试（10 个 test_*.py），本 change 不动
├── migrations/      ← 新增 2026-07-06-add-orders-raw-id.py
└── main.py / config.py / constants.py / db.py(转交 infra)
```

**依赖规则（单向，禁止反向 import）**：
```
api/ → services/ → repo/ → infra/
   ↓        ↓        ↓
  ws/    rpc/ ──────┘
models/ (ORM 定义 — 所有层可访问)
```

**远程 strategy 服务子模块 deep import 豁免**（详见 spec-deltas/server-architecture.md REQ-ARCH-004 远程豁免段）

### 2.2 `orders.raw_id` 列（v13 NEW）

| 字段 | 变更 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|---|
| `raw_id` | **NEW** | String(8) | YES | NULL | **被撤/被引用委托的本地 order_no**（v13 新增：DELETE 端点 INSERT cancel-row 时写入 = 原委托 order_no；非 cancel-row 为 NULL） |
| `user_def` | **不动** | String(255) | NO | "" | 远程 REQ-TRADE-011 决定三种取值并存（`str(strategy.id)` / `"T0"` / `"CANCEL:{orig_order_no}"`），本 change 不动 |

### 2.3 DELETE 端点 cancel-row 写入顺序变更

**改第 2 步**（其他 4 步不动）：
- INSERT cancel-row 时 `raw_id = orig.order_no`（新增字段写入）
- `user_def` 保持 `f"CANCEL:{orig.order_no}"`（v9 约定，不破坏远程 REQ-TRADE-011 兼容）
- 其余字段填充不变（v9 起已有的 5 类镜像字段）

**WS broadcast payload 增加**：`raw_id` 字段透传；`user_def` 仍透传

### 2.4 测试目录迁移（21 文件续迁）

```
server/test_*.py ×21  →  tests/server/<layer>/test_*.py
                                              （远程 2026-07-02-restructure-test-layout 已建部分目录）
                                              （server/tests/strategy/ ×10 远程 v1 不动）
```

**目标目录**：
```
tests/                              ← 已存在（含 .keep）
├── conftest.py                     ← 根级 fixtures（拆自 server/conftest.py）
└── server/                         ← 已存在（api/svc/models 子目录已建）
    ├── api/
    │   ├── test_auth.py
    │   ├── test_format_ts.py
    │   ├── test_holdings_api.py
    │   ├── test_orders_api.py
    │   ├── test_system_api.py
    │   ├── test_trades_api.py
    │   └── test_ws_endpoint.py
    ├── infra/
    │   └── test_db_session.py
    ├── models/
    │   └── test_models.py
    ├── repo/
    │   ├── test_orders_repo.py    (从 services/test_order_no.py 迁来 + 改 repo 测试)
    │   └── test_push_handlers.py  (从 services/test_push_handlers.py 迁来，因其测的是 push dispatcher 编排，归 services/ 不合适，归 repo 更准)
    ├── rpc/
    │   ├── test_rpc.py
    │   └── test_rpc_link.py
    ├── services/
    │   ├── test_config.py
    │   ├── test_guards.py
    │   ├── test_logflow.py
    │   ├── test_push_async.py
    │   ├── test_push_listener.py
    │   ├── test_reconcile.py
    │   ├── test_t0.py
    │   └── test_t0_aggregate.py
    └── test_layer_dependencies.py  (★ NEW: 依赖方向 CI 检查)
```

**保留不动**：
- `server/tests/strategy/*` ×10（远程 v1 测试，所属 services.strategy 还没迁）
- `server/conftest.py` — 根级 conftest（含 Base 重复注册 fix），迁移后保留兼容运行 `python -m pytest server/ -v` 命令
- `pytest.ini` — `testpaths = hq`（项目用 CLI 跑 `python -m pytest server/` 为主流，pytest.ini 仅兜底 hq 模块测试）

## 3. Capabilities

### Modified Capabilities
- `data-model` — 修改 §1 orders 加 `raw_id` 列（user_def 保持远程 REQ-TRADE-011 不变）
- `trading` — REQ-TRADE-003 cancel-row 字段加 raw_id（user_def 保持不变）

### New Capabilities
- `server-architecture` — 5 层模块契约（infra / repo / rpc / services / api）+ 依赖方向规则 + 文件行数约束（含远程 strategy 模块豁免规则）

### 不修改的 Capabilities（远程 owner）
- `strategy` — 远程 `2026-07-05-strategy_trade` 实现，含 4 张表 + 9 个 services 子模块 + REQ-STRAT-001..013
- `trading` REQ-TRADE-011 — 远程确立的 `user_def=str(strategy.id)` 关联约定，本 change 不动

## 4. 影响面

### 后端
- 新增：`server/infra/{mq,db}.py`、`server/repo/{orders,trades,positions,assets,system,quote_snapshots}.py`
- 修改：`server/db.py`（转交 `infra/db.py` 顶层 re-export 保兼容）、`server/rpc/transport.py`（`RPClient` 继承 `MessageQueueClient`）、`server/api/orders/cancel.py`（INSERT cancel-row 加 raw_id 字段）、`server/api/orders/schemas.py`（`OrderOut` 加 `raw_id` 字段）、`server/services/order_no.py` + `services/order_status.py` + `services/trading_clock.py`（迁 `repo/`）、`server/main.py`（`from server.infra.db import init_db`）
- 删除：原 `server/services/order_no.py` `services/order_status.py` `services/trading_clock.py`（迁 repo/ 后删除）
- 不动：`server/services/strategy/`（远程 v1，本 change 不动）、`server/api/strategy.py`（远程 v1，本 change 不动）

### DB
- `ALTER TABLE orders ADD COLUMN raw_id VARCHAR(8)`（nullable，无 default）
- 迁移脚本：`server/migrations/2026-07-06-add-orders-raw-id.py`（idempotent）

### 前端
- 不动 4 个 view（/trade /t0-trade /t-strategy /algo-strategy）的请求体字段 — 远程 strategy_trade 已实现 StrategyTrade.vue，本 change 不动
- `client/src/stores/holdings.js` 透传 `raw_id` 字段到 IDB（minimal 改动，1-2 行）

### 测试
- 21 个 `server/test_*.py` 迁 `tests/server/<layer>/`（镜像目录）
- `server/conftest.py` 不动（保留 Base 重复注册 fix）
- `pytest.ini` 不动（testpaths = hq 保持）
- 新增 `tests/server/test_layer_dependencies.py`（CI 检查分层依赖方向）

## 5. 不在本 change 范围

- ❌ 修改任何已有 handler 的控制流（仅加 raw_id 字段、改字段映射）
- ❌ 改 RPC 协议（broker `ord_stk` / `cancel_ord` 字段不变）
- ❌ 改 `next_order_no` 分配器（继续用既有逻辑）
- ❌ 改 `Order.user_def` 既有规则（远程 REQ-TRADE-011 owner；本 change 仅**追加** raw_id，不替换 user_def）
- ❌ 改 `Strategy.type` 值域（远程 `2026-07-05-strategy_trade` 锁定 `{'general','t0'}`）
- ❌ 改 `_infer_order_status` 推断函数（迁 repo/ 后行为一致）
- ❌ 改 status 码体系（v11 broker 字典对齐不变）
- ❌ 引入 Alembic（保留手写 SQL 迁移约定）
- ❌ 远程 `server/services/strategy/` 子模块 deep import 收敛（远程豁免；后续 PR 处理）
- ❌ 4 view 显式打标 0/1/2/3（如需可走 follow-up change：扩展远程 `Strategy.type` enum 为 4 值 或新增独立 `page_category` 列）

## 6. 关键设计决策（已与用户确认）

| 维度 | 选择 |
|---|---|
| strategy 主表 | **远程 owner**，本 change 不创建（4 张表 + REQ-STRAT-001..013 已在 `openspec/specs/strategy/spec.md`） |
| `Strategy.id` PK 类型 | **远程 owner**（int 自增，本 change 不动） |
| `Strategy.type` 值域 | **远程 owner**（VARCHAR(16) `{'general','t0'}`，本 change 不动） |
| `Order.user_def` 语义 | **远程 owner**（三种取值并存：本 change 不动） |
| `Order.raw_id` 列 | **本 change 新增**（String(8), nullable, 写入点仅 DELETE cancel-row） |
| `raw_id` 与 `user_def` 关系 | **并存**（cancel-row 双重字段冗余；user_def 兼容 v9 audit，raw_id 结构化推荐） |
| `raw_id` 索引 | **不新增**（cancel-row query 走 PK 覆盖） |
| 后端分层 | **5 层**（infra / repo / rpc / services / api），依赖方向 CI 检查 |
| `RPClient` 继承 | **继承** `infra.mq.MessageQueueClient`（v13 起） |
| `services/strategy/` deep import | **远程豁免**（不属本 change） |
| 测试目录镜像 | `tests/server/<layer>/`（续远程 `2026-07-02-restructure-test-layout` 未完成部分） |
| 文件行数 | 所有源文件 ≤ 250 行（CLAUDE.md 硬约束） |
| 迁移工具 | 手写 SQL 脚本（`server/migrations/` 目录约定，不引入 Alembic） |
| 数据迁移策略 | 新列 nullable 无需回填（远程 strategy_trade 已建 strategy 表，本 change 不动） |

## 7. Edge Cases

1. **历史 cancel-row 无 raw_id**：v13 之前的 cancel-row（v9-v12 期间生成的）`raw_id=NULL` + `user_def="CANCEL:{no}"` 双字段不一致；前端 query 走 LEFT JOIN 或 `IFNULL(raw_id, CAST(SUBSTR(user_def, 8) AS INT))` 兜底。
2. **新 cancel-row 双重字段一致**：`raw_id = orig.order_no` + `user_def = f"CANCEL:{orig.order_no}"`，校验时 MUST 满足 `raw_id = substr(user_def, 8)`（详见 spec-deltas/trading.md REQ-TRADE-012 Scenario）。
3. **快速双击撤单**：两次各获新 cancel-row + 各写 raw_id=原 order_no → broker 第二次可能拒 → cancel-row.status=57。前端 holdings 看到两次尝试，无数据损坏。
4. **完全成交时撤单**：cancelled_qty=0 → 仍插 cancel-row 但**不**插 cancel-trade（同 v9）；raw_id 仍写入 = 原 order_no。
5. **`holdings.applyOrderPush` 状态污染**：必须短路 cancel-row（volume=0 会被 `inferOrderStatus` 重算成 49）— v9 已处理；raw_id 透传不影响此短路逻辑。
6. **前端 IDB schema 兼容**：`OrderOut.raw_id` 是 Optional 字段，旧 IDB 数据无此字段无影响（前端 holdings store 收到 raw_id 仅透传，不强制使用）。
7. **远程 strategy API 不受影响**：`server/api/strategy.py`（远程 v1）CRUD/控制/审计端点完全不动，本 change 不改 api 层现有端点。
8. **pytest 路径冲突**：`pytest.ini: testpaths = hq` + 项目主流跑 `python -m pytest server/ -v`；本 change 迁测试到 `tests/server/` 后，CLI 跑法需更新为 `python -m pytest tests/server/ -v`（或保留 `server/` 跑法作为兼容路径）。
9. **依赖方向 CI 与远程 strategy**：远程 `services/strategy/` 内多个子模块 deep import（如 `from server.services.strategy.indicators import ma`）违反 REQ-ARCH-004，但因远程豁免，CI 需白名单处理（详见 spec-deltas/server-architecture.md REQ-ARCH-004 远程豁免段）。

## 8. Tasks（执行序列 6 commits + 1 archive）

详细见 `tasks.md`。

## 9. 验证清单（Acceptance Criteria）

### 后端架构
- [ ] `python -c "from server.infra.db import Base, SessionLocal, get_db, db_session, init_db"` 0 错误
- [ ] `python -c "from server.repo.orders import next_order_no, infer_order_status"` 0 错误
- [ ] `python -c "from server.rpc.transport import RPClient"` 0 错误（RPClient 继承 MessageQueueClient）
- [ ] 9 个原 `test_*.py` `from server.api.orders import ord_stk` 仍可 monkeypatch
- [ ] `pytest tests/server/test_layer_dependencies.py -v` 全过（依赖方向检查）

### DB 迁移
- [ ] `python server/migrations/2026-07-06-add-orders-raw-id.py` 幂等（重复运行 OK）
- [ ] `sqlite3 server/evtrade.db ".schema orders"` 包含 `raw_id` 列
- [ ] 旧 orders 数据无破坏（`SELECT COUNT(*) FROM orders` 与迁移前一致）

### 业务功能（行为一致 + raw_id 字段可用）
- [ ] POST /api/orders/place 不写 raw_id 字段（普通 strategy 委托 raw_id=NULL）
- [ ] DELETE /api/orders/{order_no} → INSERT cancel-row（`user_def="CANCEL:{orig.order_no}"` 保持 + `raw_id=orig.order_no` 新增）
- [ ] 旧 cancel-row 数据（`user_def="CANCEL:..."`，`raw_id=NULL`）查询无影响
- [ ] WS `order_update` payload 含 `raw_id` 字段
- [ ] `OrderOut` Pydantic 暴露 `raw_id: Optional[str] = None`

### 测试
- [ ] `python -m pytest server/ -v` 仍可运行（兼容旧 CLI 习惯；旧 server/test_*.py 物理删除前）
- [ ] `python -m pytest tests/server/ -v` 全过（21 迁 + 1 新依赖检查 = 22 test 文件）
- [ ] `pytest tests/server/api/test_orders_api.py -v` 仍能 monkeypatch `server.api.orders.ord_stk`
- [ ] `pytest tests/server/test_layer_dependencies.py -v` 全过

### 前端
- [ ] `npm run build` 全过（不动 4 view）
- [ ] `client/src/stores/holdings.js` 透传 `raw_id`（1-2 行改动）

### 提交
- [ ] 6 commits 按序列提交（commit message 遵循 `<type>(<scope>): <subject>` 格式）
- [ ] 每个 commit 仅包含其 task 范围文件（避免大杂烩）
- [ ] git push 通过 proxy workaround（`git -c http.proxy=`）