# Design — Layered Architecture + orders.raw_id（strategy 部分远程 owner）

> 本 design 是 v13 初版的 scope 缩小版（补集增量）。
> - **保留**：5 层架构（infra/repo/rpc/services/api）+ RPClient 继承 + tests 镜像 + server-architecture spec
> - **保留**：`orders.raw_id` 列（cancel-row 结构化冗余字段）
> - **删除**：strategy 主表（远程 `2026-07-05-strategy_trade` 已实现）/ `strategy_type` 0/1/2/3（远程 `Strategy.type` enum 锁定）/ `user_def` 重定义（远程 REQ-TRADE-011 锁定）/ PlaceOrderRequest 改造（远程 REQ-TRADE-011 已确定）/ 4 view 显式打标（如需可走 follow-up）
> - **承认远程**：`server/services/strategy/` 作为 services 层成员，但 deep import 暂豁免

## 1. 分层架构图（远程 strategy 模块也标出）

```
┌─────────────────────────────────────────────────────────────────┐
│                      Frontend (client/src)                       │
│   Trade.vue  T0Trade.vue  TStrategy.vue  AlgoStrategy.vue        │
│   StrategyTrade.vue (★ 远程 v1 新增)                              │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTP (FastAPI) + WebSocket
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  api/ — 服务端接口层 (FastAPI routers)                            │
│    ├─ orders/         (place / cancel / query)                  │
│    ├─ admin/          (sys_status / reconcile / session)        │
│    ├─ strategy.py     (★ 远程 v1)                                │
│    └─ <domain>/       (asset / holdings / positions / trades)  │
└────────────────────────────┬────────────────────────────────────┘
                             │
        ┌────────────────────┴────────────────────┐
        ▼                                         ▼
┌──────────────────────┐                ┌──────────────────────┐
│ services/ — 业务编排 │                │ rpc/ — RPC 接口类    │
│   ├─ t0/             │                │   ├─ transport.py    │
│   ├─ push/           │                │   ├─ client.py       │
│   ├─ reconcile.py    │                │   ├─ handlers.py     │
│   ├─ guards.py       │                │   └─ parsers_*.py    │
│   └─ strategy/       │ (★ 远程 v1)    │   RPClient extends   │
│      ├─ models.py    │                │     MessageQueueClient│
│      ├─ repository.py│                └──────────┬───────────┘
│      ├─ indicators.py│                           │
│      ├─ flags.py     │                           │
│      ├─ regime.py    │                           │
│      ├─ grid.py      │                           │
│      ├─ engine.py    │                           │
│      ├─ quote_consumer.py                        │
│      └─ audit.py     │                           │
└──────────┬───────────┘                           │
           │                                        │
           └────────────────┬───────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  repo/ — 仓库层（按表聚合的 CRUD）                                 │
│    ├─ orders.py       (CRUD + infer_order_status + next_order_no)│
│    ├─ trades.py                                              │
│    ├─ positions.py                                           │
│    ├─ assets.py                                              │
│    ├─ system.py  (sys_status / trading_session / fee / recon)  │
│    └─ quote_snapshots.py                                     │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  infra/ — 基类层（基础设施抽象）                                   │
│    ├─ mq.py   MessageQueueClient (aio_pika RMQ 长连接基类)       │
│    └─ db.py   DatabaseBase / SessionLocal / get_db / db_session │
└─────────────────────────────────────────────────────────────────┘
                             │
                             ▼
                    ┌────────────────┐
                    │  models/ ORM   │
                    │  (orm.py + user│
                    │   + strategy*) │
                    │  *远程 v1 models.py 包含在 services/strategy/│
                    └────────────────┘
```

**依赖方向（单向，禁止反向 import）**：
```
api/  →  services/  →  repo/  →  infra/  →  models/
  ↓         ↓            ↓
 ws/     rpc/  ────────┘
```

**远程豁免**：
- `services/strategy/` 内 9 个子模块允许 deep import（详见 spec-deltas/server-architecture.md REQ-ARCH-004 远程豁免段）
- `api/strategy.py` 顶层 re-export 允许跨层（远程 monkeypatch 兼容）
- `server/tests/strategy/*` ×10 暂不迁 `tests/server/services/strategy/`，本 change 不动

---

## 2. 关键模块契约

### 2.1 `infra/mq.py` — MessageQueueClient 基类

**职责**：aio_pika RMQ 长连接的纯传输能力，不含业务逻辑。

```python
class MessageQueueClient:
    """aio_pika RMQ 长连接基类（传输层本分）。

    子类负责：业务级 pending future 管理 / 业务 dispatcher 编排。
    """
    def __init__(self, url: str):
        self.url = url
        self.conn: Optional[aio_pika.Connection] = None
        self.channel: Optional[aio_pika.Channel] = None
        self.exchange: Optional[aio_pika.Exchange] = None
        self.reply_queue: Optional[aio_pika.Queue] = None
        self.push_queue: Optional[aio_pika.Queue] = None

    async def connect(self) -> None: ...
    async def publish(self, wire_data: bytes, routing_key: str, timeout: float = 5.0) -> None: ...
    async def listen_replies(self, on_message: Callable[[bytes], Awaitable[None]]) -> None: ...
    async def listen_pushs(self, on_message: Callable[[bytes], Awaitable[None]]) -> None: ...
    async def close(self) -> None: ...
```

**`rpc/transport.py:RPClient` 改为继承 MessageQueueClient**：
- 子类化后只保留业务级 `pending: dict[msg_id, Future]`、`call(func, headers, values)`、`_log_reply` 等
- 删掉 `connect()` 中的 aio_pika 实现细节（委托 super）
- 保留所有现有 public 行为（`get_rpc_client` / `close_rpc_client` 单例 + 测试 monkeypatch 入口）

### 2.2 `infra/db.py` — DatabaseBase 基类

**职责**：把 `server/db.py` 当前散落的 `engine / SessionLocal / Base / get_db / db_session` 重新打包成基类。

```python
# infra/db.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from contextlib import contextmanager

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    """FastAPI DI."""
    db = SessionLocal()
    try: yield db
    finally: db.close()

@contextmanager
def db_session():
    """短连接 context manager（服务层 / 背景 task / class method 用）."""
    db: Session = SessionLocal()
    try: yield db
    except Exception:
        try: db.rollback()
        except: pass
        raise
    finally: db.close()

def init_db():
    from server.models import user, orm  # 远程 v1 strategy 表已通过 services.strategy.models 注册
    Base.metadata.create_all(bind=engine)
```

**`server/db.py` 转成顶层 re-export 保兼容**：
```python
# server/db.py（兼容垫片，导完即可删除但保留 facade 模式）
from server.infra.db import (
    BASE_DIR, DB_PATH, DATABASE_URL,
    engine, SessionLocal, Base,
    get_db, db_session, init_db,
)
```

### 2.3 `repo/orders.py` — 委托表仓库

**职责**：所有 `orders` 表的 CRUD + 表级业务方法（不含跨表编排）。

```python
# repo/orders.py
from server.models.orm import Order
from server.infra.db import db_session

def next_order_no(db: Session) -> str:
    """下一 order_no（v6 起 8 位单调递增）."""
    ...

def get_by_order_no(db: Session, trd_date: str, order_no: str) -> Optional[Order]:
    ...

def insert_pending_order(db: Session, *, trd_date, order_no, user_def, stock_code,
                          order_type, price_type, price, volume) -> Order:
    """INSERT status=48 待报行（place 第 3 步用；user_def 透传 = str(strategy.id) / 'T0' / 默认空）."""
    ...

def insert_cancel_row(db: Session, *, orig: Order, cancel_order_no: str) -> Order:
    """INSERT cancel-row（order_flag=1, user_def='CANCEL:{orig.order_no}' 不变 + raw_id=orig.order_no v13 NEW）."""
    ...

def infer_order_status(order: Order, broker_status: Optional[str] = None) -> str:
    """v11 broker 字典推断（保持现有逻辑，迁 repo 后行为不变）."""
    ...
```

### 2.4 `services/` 缩小

**保留**（跨表 / RPC 编排）：
- `services/t0/` — T0 聚合（已拆分）
- `services/push/` — push 编排（dispatcher / routes / run_handlers / ord / trd）
- `services/reconcile.py` — 对账（RPC + 多表）
- `services/guards.py` — 鉴权守卫
- `services/t0/core.py` — T0 业务核心
- `services/strategy/` — **远程 v1，不动**

**迁出**（去 `repo/`）：
- `services/order_no.py` → `repo/orders.py:next_order_no`
- `services/order_status.py` → `repo/orders.py:infer_order_status`
- `services/trading_clock.py` → `repo/system.py:trading_clock_*`

---

## 3. `orders.raw_id` 列 schema

### schema 变更（差量，最小侵入）

```python
# server/models/orm.py - Order 类追加（user_def 字段不动）
class Order(Base):
    # ... 现有字段不动 ...
    raw_id = Column(String(8), nullable=True)  # v13 NEW: cancel-row 写 = 原 order_no
    # user_def 字段保持远程 REQ-TRADE-011 三种取值并存
```

### 写入路径（cancel.py 第 2 步更新 — 仅加字段，不改 user_def）

```python
# server/api/orders/cancel.py — 第 2 步 INSERT cancel-row
cancel_row = Order(
    trd_date=orig.trd_date,
    order_no=next_order_no(db),
    user_def=f"CANCEL:{orig.order_no}",  # v9 不变
    raw_id=orig.order_no,                # ★ NEW 字段写入
    stock_code=orig.stock_code,
    order_type=orig.order_type,
    price_type=orig.price_type,
    price=orig.price,
    volume=0,
    order_flag=1,
    status="48",
    order_time=format_ts(tz='local'),
)
```

### 冗余校验

cancel-row 写入后 MUST 满足：
- `user_def = f"CANCEL:{raw_id}"`（即 `substr(user_def, 8) = raw_id`）
- `order_flag = 1`
- `raw_id IS NOT NULL`

### Pydantic schema 差量

```python
# server/api/orders/schemas.py — 增量修改
class OrderOut(BaseModel):
    # ... 现有字段不动 ...

    # ★ NEW v13
    raw_id: Optional[str] = None

    # 不变：user_def 继续透传（远程 REQ-TRADE-011 owner）
```

---

## 4. 依赖方向规则（防腐败）

**项目级硬约束（CLAUDE.md + 本 change §1）**：

| 上层 | 可 import | 不可 import |
|------|-----------|------------|
| `api/` | `services/` `rpc/` `repo/` `models/` `infra/` `ws/` `auth/` `utils/` `enums/` `middleware/` | 无（api 是最外层） |
| `services/` | `repo/` `rpc/` `models/` `infra/` `utils/` `enums/` | `api/` |
| `repo/` | `models/` `infra/` `utils/` | `services/` `rpc/` `api/` |
| `rpc/` | `models/` `infra/` `utils/` `services/push/` (push dispatcher) | `api/` `repo/` |
| `infra/` | 无（最底层） | 任何上层 |

**验证方法**：CI 加一个 `tests/server/test_layer_dependencies.py`，用 `ast` 解析所有 `import server.X` 语句，断言上层不 import 非法下层。

**远程 strategy 豁免**：
- `server/services/strategy/*.py`（9 个子模块）相互之间的 deep import（如 `from .indicators import ma`）允许
- `server/services/strategy/*` 内的 import 不走 `__init__.py` 全符号 re-export（远程 v1 没建）
- CI 白名单：上述 deep import 不报错

---

## 5. 关键变更流程图

### 5.1 DELETE 端点完整流程（v13 改第 2 步，最小侵入）

```
DELETE /api/orders/{order_no}?trd_date=YYYYMMDD
       │
       ▼
┌─────────────────────────────────────────────────────────────┐
│ api/orders/cancel.py — 5 步流程                                │
│  Step 1: Pre-checks（status ∈ {48,49,50}, order_id 存在）    │
│  Step 2: ★ INSERT cancel-row（v13 加 raw_id）                │
│           orders.user_def = f"CANCEL:{orig.order_no}" (v9 不变)│
│           orders.raw_id = orig.order_no (v13 NEW)            │
│           orders.order_flag = 1                              │
│           orders.status = "48" (broker UNREPORTED sentinel)  │
│  Step 3: Call RPC cancel_order(order_id=orig.order_id)      │
│  Step 4: 分支                                                │
│           ack==0 → cancel-row.status='54' + 插 cancel-trade │
│           ack!=0 → cancel-row.status='57'                   │
│  Step 5: WS broadcast（payload 含 raw_id + user_def）        │
└─────────────────────────────────────────────────────────────┘
```

### 5.2 下单流程（v13 不动 — 远程 REQ-TRADE-011 owner）

`POST /api/orders/place` 4 步流程保持 v11 broker 码业务写入点不变；`Strategy.type` 值域（远程 v1 锁定 `{'general','t0'}`）和 `Order.user_def = str(strategy.id)`（远程 REQ-TRADE-011）均不修改。

---

## 6. 测试迁移映射表（21 续迁 + 1 新增）

| 原路径 | 新路径 | 备注 |
|--------|--------|------|
| `server/test_auth.py` | `tests/server/api/test_auth.py` | 测 api/auth.py |
| `server/test_config.py` | `tests/server/services/test_config.py` | 测根 config.py（util 类） |
| `server/test_db_session.py` | `tests/server/infra/test_db_session.py` | ★ 迁到 infra 层（新归属） |
| `server/test_format_ts.py` | `tests/server/api/test_format_ts.py` | utils/time helper |
| `server/test_guards.py` | `tests/server/services/test_guards.py` | services/guards.py |
| `server/test_holdings_api.py` | `tests/server/api/test_holdings_api.py` | 不变 |
| `server/test_logflow.py` | `tests/server/services/test_logflow.py` | utils/logflow helper |
| `server/test_models.py` | `tests/server/models/test_models.py` | models/orm.py |
| `server/test_order_no.py` | `tests/server/repo/test_orders_repo.py` | ★ 迁到 repo 层 + 改名 |
| `server/test_orders_api.py` | `tests/server/api/test_orders_api.py` | 不变 |
| `server/test_push_async.py` | `tests/server/services/test_push_async.py` | services/push/ |
| `server/test_push_handlers.py` | `tests/server/repo/test_push_handlers.py` | ★ 测 push 编排迁 repo 不准，**改迁 services/ 更准**（待 task 决定） |
| `server/test_push_listener.py` | `tests/server/services/test_push_listener.py` | rpc/transport.py listener 测试 |
| `server/test_reconcile.py` | `tests/server/services/test_reconcile.py` | services/reconcile.py |
| `server/test_rpc.py` | `tests/server/rpc/test_rpc.py` | rpc/handlers.py |
| `server/test_rpc_link.py` | `tests/server/rpc/test_rpc_link.py` | rpc/transport.py |
| `server/test_system_api.py` | `tests/server/api/test_system_api.py` | api/system.py |
| `server/test_t0.py` | `tests/server/services/test_t0.py` | services/t0/core.py |
| `server/test_t0_aggregate.py` | `tests/server/services/test_t0_aggregate.py` | services/t0/aggregate_api.py |
| `server/test_trades_api.py` | `tests/server/api/test_trades_api.py` | 不变 |
| `server/test_ws_endpoint.py` | `tests/server/api/test_ws_endpoint.py` | api/ws/endpoint |
| 新增 | `tests/server/repo/test_orders_repo.py` | 覆盖 repo 层新接口 |
| 新增 | `tests/server/test_layer_dependencies.py` | 依赖方向规则 CI 检查 |

**不动**：
- `server/tests/strategy/*` ×10（远程 v1 测试）
- `server/conftest.py` — 根级 conftest（含 Base 重复注册 fix）
- `pytest.ini` — `testpaths = hq` 保持

**import 路径统一改写规则**：
- `from server.X` 全部保持不变（`server/` 是根包，迁移不破坏）
- 唯一改的是**测试文件自己的位置**（从 `server/test_X.py` → `tests/server/<layer>/test_X.py`）
- 文件内部的 `from server.foo import bar` 一律不动

**conftest.py 处理**：
- 根级 fixture（DB engine / SessionLocal / test DB）→ 保留 `server/conftest.py` 不动（远程 v1 已建兼容机制）
- api 层 fixture（TestClient）→ 远程 v1 已有（`tests/server/api/conftest.py` if exists），本 change 不动
- rpc 层 fixture（mock MQ）→ 远程 v1 已有（`tests/server/rpc/conftest.py` if exists），本 change 不动
- **唯一新增**：`tests/server/conftest.py` 顶层空文件（如果远程 v1 没建），目的是让 `pytest tests/server/` collect 时自动识别子目录

---

## 7. 风险与回滚

| 风险 | 影响 | 缓解 | 回滚 |
|------|------|------|------|
| monkeypatch 路径变化 | 测试大批失败 | `server/api/orders/__init__.py` 顶层 re-export 不变 | 不需要回滚（已守住） |
| `RPClient` 继承改动破坏现有连接 | 全部 RPC 失败 | 继承不改 `connect()` 业务语义；用现有 RPC 测试守住 | revert commit #2 |
| `raw_id` nullable + 旧数据 | 旧 orders 行 raw_id=NULL | 迁移脚本不强制回填；查询端 NULL 走 fallback | 不需要回滚 |
| 远程 strategy API 路径冲突 | 远程 `server/api/strategy.py` 顶层 re-export 引用 services.strategy.X 违反新分层 | 远程豁免规则允许 deep import | 后续 PR 收敛 |
| test 迁移后 pytest collect 路径错 | 全部测试找不到 | 保留 `server/conftest.py` 兼容旧 CLI 跑法；新建 `tests/server/conftest.py` 让 `pytest tests/` 可用 | revert commit #5 |
| 6 commit 链式依赖 | 中间任何失败阻塞后续 | 每个 commit 跑 `python -c "import server.X"` 守住；可单独 revert | revert 单个 commit 不影响其他 |
| 远程 services/strategy/ 子模块 deep import 污染新分层 | CI 误报 | CI 白名单处理 `services/strategy/` 内部 import | 不需要回滚（豁免规则） |

**回滚总策略**：6 个 commit 整体 revert 即可回到 v12 + 远程 strategy_trade 状态（DB 迁移脚本反向：`ALTER TABLE orders DROP COLUMN raw_id`）。