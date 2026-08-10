# 数据访问层重写 + 结构整理：Tables Core Table 注册 / 删 ORM / 删垫片 / 清废弃目录 / 拆 HTTP 客户端

> ⚠️ **本 change 不再是「不改逻辑」**——A 组（方案 1）经用户确认接受数据访问层引擎重写。
> 与 B/C/D（纯结构整理）混合在一起，review/回滚粒度变粗。
> 详见 [design.md](./design.md)。

## Why

EvTrade 后端存在两套并行的数据访问范式，外加三处纯结构性债务。本 change 一次性清理：

### 债务 A：ORM 双轨制（数据访问层引擎重写）

`server/models/orm.py`（452 行，9 个 declarative ORM 类）与 `server/tables/`（19 文件，
`TableBase` + `Row` 自定义范式）并存。`orm.py` 的 `get_active_*` helper 已内部走 `tables.SysStatus`，
`reconcile.py` 已混用两套——迁移基础已就位但未收口。

**阻塞点**：删 `orm.py` 后 `Base.metadata` 空，`alembic autogenerate` + `init_db()` 失去扫描源。
同时 `services/strategy/models.py`（316 行，7 个 strategy ORM 类）也是注册源。

**方案选择**（详见 design.md §三方案对比）：用户选**方案 1**——彻底重写 `tables/` 改用
SQLAlchemy Core `Table` 对象注册 `Base.metadata`，`orm.py` + `services/strategy/models.py`
整文件删除。接受重写 codegen + TableBase 的工程量。

### 债务 B：`server/db.py` 兼容垫片（16 行纯 re-export）

`server/db.py` 是 v13 留下的 facade，实际实现已在 `server/infra/db.py`（329 行）。
20 个文件仍通过 `from server.db import` 访问。删除垫片，引用方直接走 `infra.db`。

### 债务 C：`kb/` 废弃知识库目录

`kb/README.md` 自述 DEPRECATED（2026-06-28），内容已并入 `openspec/specs/`。
全项目零代码引用确认。目录删除。

### 债务 D：`client/src/api/index.js` HTTP 基础设施与业务 endpoint 混装（338 行）

axios 实例 + 拦截器 + RPC 解包（横切关注点）与 20+ 业务 endpoint 方法混在一个文件。
拆为 `api/http.js`（基础设施）+ `api/index.js`（业务）。

## What Changes

### A 组 — Tables Core Table 重写 + ORM 删除

#### A.0 重写 codegen 生成器

- **重写** `scripts/gen_tables.py`：读 `INFORMATION_SCHEMA` → 生成
  `Table(..., Base.metadata, Column(...), ...)` 而非字符串元数据类
- **保留** type hint 生成（IDE 智能提示）
- **新增** `#codegen:preserve-below` 标记段机制：手写 `__table_args__` 约束（如
  `CheckConstraint("id = 1")`）在标记后不被覆盖
- **类型映射**：MySQL → SQLAlchemy Column（design.md D2）

#### A.1 重写 `server/tables/base.py`

- **`TableBase`**：持有 `__table__: sqlalchemy.Table`，方法改用 Core API
  - `query_one` → `Table.select().where(...)`
  - `add_one` → `Table.insert().values(...)`
  - `update_one` → `Table.update().where(...).values(...)`
  - `delete_one` → `Table.delete().where(...)`
  - `query_all` → `Table.select().order_by(...)`
  - `upsert_one` → `mysql.insert(...).on_duplicate_key_update(...)`
- **`Row` 类不变**：仍轻量字典 + 属性访问兼容，`_row_from_mapping` 从 `result.mappings()` 构造
- **保留** `aggregate` / `scalar_query` / `exec_sql` 字符串 SQL 入口（复杂聚合兼容）
- **`Row.update()`** 改用 `_owner_class.__table__.update().where(...).values(...)`

#### A.2 重新生成 19 个 tables/*.py

- 跑改写后的 `gen_tables.py` 一键重生成
- 手动检查每个生成文件的 `__table_args__` 约束段（`orm.py` 现有的 `Index` / `CheckConstraint`
  / `UniqueConstraint` 需迁到生成文件的 `__table_args__` + `#codegen:preserve-below`）

#### A.3 切换 metadata 注册源

- `server/alembic/env.py` L46：`from server.models import user, orm` →
  `import server.tables`（触发 Core Table 注册到 `Base.metadata`）
- `server/infra/db.py` L192 `init_db()`：同上
- **验证**：`alembic revision --autogenerate -m "verify-metadata-swap"` 生成**空 diff**
  （证明新旧 metadata 等价）

#### A.4 业务代码迁移（按 design.md D6 模式，分 4 phase）

| Phase | 风险 | 文件 | ORM 类 |
|-------|------|------|--------|
| A.4.1 | 🟢 低 | guards.py, repo/system.py, quote_consumer.py | SysStatus, QuoteSnapshot |
| A.4.2 | 🟡 中 | strategy/engine.py, strategy/t0/engine.py, api/admin/sys_status.py | Order |
| A.4.3 | 🟠 中高 | t0/aggregators.py, t0/pnl.py, t0/core.py | Order, Trade（类型签名） |
| A.4.4 | 🔴 高 | services/reconcile.py | Position, Asset（链式 insert/delete） |

#### A.5 迁出 `services/strategy/models.py` 业务方法

该文件有 6 个 ORM 类业务方法（StrategyRegime flags getter/setter、StrategyAudit
flags_active + action_payload getter/setter）+ 2 个 JSON helper（`_json_dumps`/`_json_loads`）。
迁到 `services/strategy/repository.py` 或对应 service，改为对 `Row` 操作的纯函数。

#### A.6 迁移 `services/strategy/models.py` 7 个 strategy ORM 类

`Strategy / StrategyRegime / StrategyGrid / StrategyAudit / StrategyScript /
StrategyTask / StrategyScriptAudit` 的引用方迁到 `tables.*` 对应类。

#### A.7 删除

- `server/models/orm.py`（452 行，9 类 + 2 helper）
- `server/models/user.py` 里的 `User(Base)` 类（如 `tables/users.py` 已有 `Users`）
- `server/services/strategy/models.py`（316 行，7 类 + 6 方法 + 2 helper）
- `server/models/__init__.py`（若变空）

### B 组 — 删除 `server/db.py` 垫片

- 20 个引用方 `from server.db import` → `from server.infra.db import`
- 删除 `server/db.py`
- 详见 tasks.md B 组

### C 组 — 删除 `kb/` 废弃目录

- 删除 `kb/` 整个目录（零代码引用确认）
- 详见 tasks.md C 组

### D 组 — 拆分 `client/src/api/index.js`

- 新建 `client/src/api/http.js`（axios 实例 + 拦截器 + RPC 解包 + token）
- `api/index.js` 只留业务 endpoint
- per-feature API 文件 `http` 导入路径调整
- 详见 tasks.md D 组

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- **server-architecture**：infra 层 `Base = declarative_base()` 降级为纯 metadata 容器；
  `tables/` 成为表结构真源；`server/db.py` + `models/orm.py` + `services/strategy/models.py`
  删除，5 层架构的「models/」层消失（表定义归 `tables/`，业务方法归 `services/`）
- **data-model**：spec 中「同步到 `server/models/orm.py` 和 `server/db.py`」→
  「表结构真源为 `server/tables/*.py`（codegen 生成）+ `scripts/gen_tables.py`；
  metadata 注册源为 `server/infra/db.py:Base.metadata`」
- **strategy**：`services/strategy/models.py` 7 个 ORM 类删除，表定义归 `tables/strategy*.py`，
  flags/payload 等 getter/setter 改为对 `Row` 操作的纯函数
- **frontend**：`api/index.js` 拆为 `api/http.js`（基础设施）+ `api/index.js`（业务）

## Impact

- **代码**：
  - 重写：`scripts/gen_tables.py`、`server/tables/base.py`
  - 重生成：19 个 `server/tables/*.py`
  - 删除：`server/db.py` + `server/models/orm.py` + `server/models/user.py`(部分) +
    `server/models/__init__.py` + `server/services/strategy/models.py` + `kb/` 目录
  - 新建：`client/src/api/http.js`
  - 修改：~30 个文件的 import 路径 + 数据访问 API 调用形态
- **逻辑**：
  - B/C/D 零业务逻辑改动
  - A 是数据访问层引擎重写——业务**行为**不变，但**底层 SQL 构造方式**从字符串拼接
    改为 SQLAlchemy Core 表达式（语义等价，但 upsert/事务边界等需 e2e 验证）
- **风险**：
  - A.0-A.2 codegen + TableBase 重写是底层改动，影响所有 tables 调用方
  - A.4.4 reconcile Position/Asset 链式写是高风险点
  - metadata 切换若不等价，alembic 后续迁移会生成错误 diff
- **缓解**：每个 phase 独立验证 + commit；A.3 用 `alembic revision --autogenerate` 空 diff
  验证 metadata 等价；A.4 各 phase 跑对应 e2e

## 不在本 change 范围

- 巨型文件拆分（strategy/service.py 999 行、T0Trade.vue 1232 行等）——另立 change
- 前端 DataTableView 迁移收口（6 个 views 仍用 el-table）——另立 change
- evctl.py 784 行拆分——另立 change
