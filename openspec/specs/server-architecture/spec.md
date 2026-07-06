# server-architecture — 后端 5 层模块契约

## Purpose

EvTrade 后端经过 v5-v13 多轮迭代，积累了 100+ Python 文件（`server/` 目录下），按"领域 + 工具 + RPC + API" 4 类混合组织。本 spec 引入**显式 5 层架构**（infra / repo / rpc / services / api），强制单向依赖方向，约束模块边界，使：

- 单文件职责清晰（每层文件 ≤ 250 行 CLAUDE.md 硬约束）
- 跨层修改可预测（依赖方向规则防腐败）
- 新增功能有归属（按业务归属到对应层）
- 测试镜像目录清晰（`tests/server/<layer>/`）

**横向分层 vs 纵向业务模块**：本 spec 是横向分层（infra/repo/rpc/services/api）；远程 `2026-07-05-strategy_trade` 的 `services/strategy/` 是纵向业务模块。两者正交。

## 5 层架构

```
api/      ← 服务端接口层（FastAPI routers，前端调用）
services/ ← 业务编排层（跨表 / RPC 组合，跨模块业务流，含 services/strategy/）
rpc/      ← RPC 接口层（消息队列交互，业务级 RPC 调用）
repo/     ← 仓库层（按表聚合的 CRUD，封装 ORM 操作）
infra/    ← 基类层（基础设施抽象，aio_pika / SQLAlchemy 顶层封装）
```

**依赖方向（严格单向，禁止反向 import）**：

```
api/  →  services/  →  repo/  →  infra/  →  models/
  ↓         ↓            ↓
 ws/     rpc/  ────────┘
```

## Requirements

### REQ-ARCH-001: 5 层模块边界

#### infra/ 基类层
- **包含**：消息队列基类（`MessageQueueClient`）、数据库基类（`DatabaseBase`/`SessionLocal`/`get_db`/`db_session`）
- **职责**：封装第三方依赖（aio_pika / SQLAlchemy）的细节，对上层只暴露纯接口
- **不允许 import**：任何上层（api / services / rpc / repo）；仅可 import `server.models.orm`（如需要 type hint）和第三方库
- **文件**：当前 ≤ 2 个（`mq.py` + `db.py`）

#### repo/ 仓库层
- **包含**：按表聚合的 CRUD 函数（`repo.orders / repo.trades / repo.positions / repo.assets / repo.system / repo.quote_snapshots`）
- **职责**：封装单表的查询/插入/更新/删除 + 表级业务方法（如 `next_order_no` / `infer_order_status`）；不含跨表编排
- **允许 import**：`server.models.*` / `server.infra.db` / `server.utils.*`
- **不允许 import**：`server.services.*` / `server.rpc.*` / `server.api.*`
- **文件目标**：每个 `repo/<domain>.py` ≤ 250 行
- **不包含** strategy 表 CRUD（远程 `2026-07-05-strategy_trade` 已实现 `server/services/strategy/repository.py`；本 spec 不动 strategy 模块）

#### rpc/ RPC 接口层
- **包含**：消息队列传输（`RPClient`）+ 业务级 RPC 调用（`handlers.py:qry_*/ord_*/cancel_*`）+ 报文解析（`parsers_*.py`）
- **职责**：通过 MQ 与 broker（xtquant）通信；封装 RPC 调用模式（call / reply / push / dispatch）
- **允许 import**：`server.models.*` / `server.infra.*` / `server.utils.*` / `server.services.push.*`（push dispatcher）
- **不允许 import**：`server.api.*` / `server.repo.*`
- **继承约束**：`RPClient` MUST 继承 `infra.mq.MessageQueueClient`

#### services/ 业务编排层
- **包含**：跨表 / 跨 RPC 的业务流（`services.t0` / `services.push` / `services.reconcile` / `services.guards` / `services.strategy`）
- **职责**：组合多个 repo 函数 + RPC 调用 + 业务规则（如 T0 配平、对账、push 编排、strategy 引擎）
- **允许 import**：`server.repo.*` / `server.rpc.*` / `server.models.*` / `server.infra.*` / `server.utils.*`
- **不允许 import**：`server.api.*`
- **包含远程 strategy**：`server/services/strategy/` 由远程 `2026-07-05-strategy_trade` 创建（包含 models / repository / indicators / flags / regime / grid / engine / quote_consumer / audit 等子模块）；本 spec 承认其为 services 层成员

#### api/ 服务端接口层
- **包含**：FastAPI routers（`api/orders/` / `api/admin/` / `api/<domain>.py` / `api/strategy.py`）
- **职责**：暴露 HTTP/WS 端点；调用 services + repo；参数校验（Pydantic）；权限守卫（Depends）
- **允许 import**：所有下层（services / rpc / repo / models / infra / ws / auth / utils / enums / middleware）
- **不允许 import**：无（api 是最外层）
- **包含远程 strategy**：`server/api/strategy.py` 由远程 `2026-07-05-strategy_trade` 创建（CRUD + 控制 + 审计查询 REST 端点）

### REQ-ARCH-002: 单向依赖方向强制

- **强制规则**：每个 Python 文件 `import server.X` 必须满足 `X` 的层 ≤ 当前文件所在层
- **层优先级**（数字越小越内层）：
  - `infra` = 0
  - `models` = 0（与 infra 同级，纯定义）
  - `repo` = 1
  - `rpc` = 1（与 repo 同级，但 rpc 不依赖 repo；rpc 只依赖 infra）
  - `services` = 2
  - `ws` / `auth` / `middleware` / `utils` / `enums` = 跨层工具，按需 import
  - `api` = 3（最外层）
- **跨同级层规则**：
  - `rpc` 不可 import `repo`（同级且 rpc 在协议层，repo 在数据层）
  - `services` 可同时 import `repo` + `rpc`
- **CI 检查**：`tests/server/test_layer_dependencies.py` 用 `ast` 解析所有 `import server.X` 语句，断言：
  ```python
  LAYER_PRIORITY = {
      "infra": 0, "models": 0,
      "repo": 1, "rpc": 1,
      "services": 2,
      "ws": 2, "auth": 2, "middleware": 2, "utils": 2, "enums": 2,
      "api": 3,
      "main": 3, "db": 0, "config": 0, "constants": 0,  # 兼容垫片
  }
  for src_layer, src_file in enumerate(all_py_files):
      for imported_module in parse_imports(src_file):
          if imported_module starts with "server.":
              target_layer = layer_of(imported_module)
              if LAYER_PRIORITY[target_layer] > LAYER_PRIORITY[src_layer]:
                  # 例外：api/orders/__init__.py 顶层 re-export 允许跨层（兼容 monkeypatch）
                  if src_file.endswith("__init__.py") and "re-export" in file_docstring:
                      continue
                  fail(f"{src_file} imports {imported_module} (forbidden)")
  ```
- **例外**（白名单）：
  - `server/api/orders/__init__.py` — 顶层 re-export 允许跨层（test_orders_api.py monkeypatch 目标）
  - `server/api/strategy.py` — 远程 strategy_trade 顶层 re-export 允许跨层
  - `server/db.py` / `server/main.py` / `server/config.py` / `server/constants.py` — 兼容垫片/入口文件，不做层级检查
  - `server/services/push/*` — push dispatcher 编排层，跨 rpc + repo
  - `server/infra/db.py` — `init_db()` 需要 import `strategy.models` 注册到 `Base.metadata`（后续 PR 收敛为 model registry）
  - `server/rpc/transport.py` + `server/rpc/client.py` — RPClient 业务方法编排跨 rpc + repo

### REQ-ARCH-003: 文件行数约束

- **硬约束**：每个源文件 ≤ 250 行（CLAUDE.md）
- **超过处理**：立即拆分为同模块下的子文件（按职责）
- **CI 检查**：`tests/server/test_layer_dependencies.py::test_no_250_line_violation` 用 `wc -l` 检查所有源文件
- **迁移期豁免**：迁移中的 facade 文件（如 `server/db.py` 转兼容垫片）暂不计入（但目标 ≤ 50 行）
- **远程豁免**：`server/services/strategy/` 子模块（远程 `2026-07-05-strategy_trade` 实现）需在后续 PR 中逐步拆薄到 ≤ 250 行；本 spec 不动
- **v13 已知超出**（拆分由后续 PR 处理）：
  - `server/repo/orders.py` (280 行)
  - `server/rpc/transport.py` (380 行)
  - `server/models/orm.py` (344 行)
  - `server/services/t0/aggregators.py` (283 行)
  - `server/api/t0_stats.py` (253 行)

### REQ-ARCH-004: 统一入口规则

- 每个模块目录 MUST 有 `__init__.py` 作为**统一入口**
- 外部模块 MUST 仅从 `__init__.py` 导入暴露的功能
- 禁止"深层路径引入"（如 `from server.services.t0.core import calc_net_amount` → 应改为 `from server.services.t0 import calc_net_amount`）
- **CI 检查**：`grep -r "from server.X.Y.Z import" server/ tests/` 0 结果（除 `__init__.py` 自身）
- **远程豁免**：`server/services/strategy/` 多个子模块（repository / indicators / flags / regime / grid / engine 等）允许 deep import（远程 facade 模式没建 `__init__.py` 全符号 re-export）；本 spec 不动远程 strategy 子模块

### REQ-ARCH-005: 模块依赖图（文档化）

- **维护位置**：`docs/architecture/server-layers.md`（待建）
- **内容**：
  - 当前 5 层目录树（含每个文件用途 1-2 句）
  - 关键调用链图（place_order / cancel_order / reconcile / push handler / strategy engine 等）
  - 新增功能归属决策树（"X 业务改放进哪层"）
- **更新时机**：每次 PR 涉及层调整时同步更新

## Scenario: 分层违规被 CI 拦下

- **WHEN** 开发者新增 `server/repo/orders.py` 中的 import 段：`from server.api.orders import router`
- **THEN** `pytest tests/server/test_layer_dependencies.py` 报错：`server/repo/orders.py imports server.api.orders (forbidden: layer 1 → layer 3)`
- **修复**：repo 不应反向 import api；如确需 router 实例化，应通过 DI 注入或挪到 services 层

## Scenario: 文件超 250 行被 CI 拦下

- **WHEN** `server/services/push/dispatcher.py` 增长到 280 行
- **THEN** `pytest tests/server/test_layer_dependencies.py` 报错：`server/services/push/dispatcher.py: 280 lines (>250)`
- **修复**：按职责拆分为 `dispatcher_main.py` + `dispatcher_routes.py` + `dispatcher_trd.py` 等

## Scenario: monkeypatch 路径稳定

- **WHEN** 测试用 `monkeypatch.setattr("server.api.orders.ord_stk", mock)`
- **THEN** 路径 MUST 命中（即便 `ord_stk` 实际定义在 `server/rpc/handlers.py`，`server/api/orders/__init__.py` 顶层 re-export 必须保留 `ord_stk` 名字）

## Scenario: 远程 strategy 子模块豁免

- **WHEN** 开发者新增 `server/services/strategy/engine.py` 中的 import 段：`from server.services.strategy.indicators import ma`
- **THEN** 路径虽然违反 REQ-ARCH-004（应走 `__init__.py`），但因远程 `2026-07-05-strategy_trade` 豁免，CI 不报错
- **后续工作**：远程 strategy 模块应建 `__init__.py` 全符号 re-export；本 spec 不动

## 不在本 spec 范围

- ❌ 跨层重构的**具体实施计划**（见 `changes/2026-07-06-layered-architecture-and-strategy-master/tasks.md`，已 archive）
- ❌ 每个 repo 函数的**具体实现**（见 `data-model/spec.md` §N 字段约束 + `trading/spec.md` REQ-TRADE-NNN 业务约束）
- ❌ 第三方库（aio_pika / SQLAlchemy）的 API 契约（见各自官方文档）
- ❌ 远程 `services/strategy/` 子模块的 deep import 收敛（远程 `2026-07-05-strategy_trade` 豁免；后续 PR 处理）
