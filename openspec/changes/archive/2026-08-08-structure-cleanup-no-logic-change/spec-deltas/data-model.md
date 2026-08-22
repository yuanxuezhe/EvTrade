## MODIFIED Requirements

### Requirement: 表结构真源切换 — `models/orm.py` → `tables/*.py`（Core Table）

方案 1 重写后，表结构真源从 `server/models/orm.py`（declarative ORM）切换到
`server/tables/*.py`（SQLAlchemy Core `Table`，codegen 生成）。metadata 注册源为
`server/infra/db.py:Base.metadata`。

#### 变更前（spec 现状）

spec L6「任何表结构变更（加列、改类型、调 PK、改约束）必须先改本 spec，再同步到
`server/models/orm.py` 和 `server/db.py`。」

#### 变更后

「任何表结构变更（加列、改类型、调 PK、改约束）必须先改本 spec，再**改 DB 后跑
`python scripts/gen_tables.py` 重新生成 `server/tables/*.py`**（Core Table 定义，
注册到 `server/infra/db.py:Base.metadata`）。`server/models/orm.py` 和 `server/db.py`
已删除，不再是同步目标。」

#### Scenario: 表结构变更工作流

- **WHEN** 维护者需要加列 / 改类型 / 调 PK
- **THEN** 1) 改 `openspec/specs/data-model/spec.md` 对应章节
- **AND** 2) 手动 ALTER DB（或写 alembic migration）
- **AND** 3) `python scripts/gen_tables.py` 重新生成对应 `tables/<table>.py`
- **AND** 4) 若有手写约束（`__table_args__` + `#codegen:preserve-below`），检查约束仍保留

#### Scenario: metadata 注册源唯一

- **WHEN** `alembic autogenerate` 或 `init_db().create_all()` 执行
- **THEN** metadata 来自 `import server.tables` 触发的 Core Table 注册
- **AND** 不依赖 `server/models/orm.py`（已删除）或 `server/db.py`（已删除）

#### Scenario: ORM 注释迁移到 codegen

- **WHEN** 维护者查看 `server/tables/orders.py` 的字段定义
- **THEN** codegen 生成的 `Column(...)` 定义 + `#codegen:preserve-below` 段的手写约束
  共同构成表结构
- **AND** `orm.py` 类注释中的 v5/v7/v9/v10/v13/v18/v66 schema 改动历史保留在
  `openspec/specs/data-model/spec.md`（本 spec 是 schema 知识库）
