## MODIFIED Requirements

### Requirement: infra/ 基类层 — `Base` 降级为纯 metadata 容器

方案 1 重写后，`server/infra/db.py` 的 `Base = declarative_base()` **不再被任何业务类继承**，
只作为 `MetaData` 容器供 `Table(..., Base.metadata, ...)` 注册。表结构真源从 `server/models/orm.py`
（declarative ORM）切换到 `server/tables/*.py`（SQLAlchemy Core `Table`，codegen 生成）。

#### 变更前（spec 现状）

- spec L37-40 描述 infra 层「包含 `DatabaseBase`/`SessionLocal`/`get_db`/`db_session`」
  且「文件 ≤ 2 个（`mq.py` + `db.py`）」
- spec L108 将 `server/db.py` 列为「兼容垫片/入口文件，不做层级检查」
- spec L118 将 `server/db.py` 列为「迁移期豁免」
- spec L46 `from server.models import user, orm` 作为 alembic 注册源
- spec L192 `init_db()` 同样 import `server.models.orm` 注册

#### 变更后

- `server/db.py` 删除（B 组）
- `server/models/orm.py` 删除（A 组，452 行 9 类 declarative ORM）
- `server/models/user.py` 的 `User(Base)` 删除（若引用方已迁 `tables.Users`）
- `server/services/strategy/models.py` 删除（A 组，316 行 7 类 strategy ORM）
- `server/infra/db.py` 的 `Base` 保留，但**仅作 metadata 容器**——无类继承它
- `alembic/env.py` L46 + `init_db()` L192 改为 `import server.tables` 触发 Core Table 注册
- spec L40「文件 ≤ 2 个（`mq.py` + `db.py`）」→「文件 ≤ 2 个（`mq.py` + `infra/db.py`）」
- spec L108 `server/db.py` 整行删除
- spec L118 `server/db.py` 迁移期豁免整行删除

### Requirement: tables/ 层 — 持有 SQLAlchemy Core Table 对象

`server/tables/base.py` 的 `TableBase` 重写后持有 `__table__: sqlalchemy.Table` 属性，
方法从字符串 SQL 拼接改为 Core API（`Table.select()` / `Table.insert()` / `Table.update()` /
`Table.delete()`）。`Row` 类不变（轻量字典 + 属性访问兼容）。

#### Scenario: TableBase 方法走 Core API

- **WHEN** 调用 `Orders.query_one(order_no=x)` / `Orders.add_one(row)` / `o.update()` 等任意方法
- **THEN** 内部构造 `cls.__table__.select().where(...)` / `.insert().values(...)` /
  `.update().where(...).values(...)` 等 Core 表达式
- **AND** 不再有 `text(f"SELECT * FROM ... WHERE ...")` 字符串拼接

#### Scenario: tables/ 是 metadata 注册源

- **WHEN** `import server.tables` 执行
- **THEN** 19 个表的 `Table(..., Base.metadata, Column(...), ...)` 全部注册到 `Base.metadata`
- **AND** `alembic autogenerate` 和 `init_db().create_all()` 无需 import `server.models.orm`

#### Scenario: 5 层架构无 models/ 层

- **WHEN** 检查 `server/models/` 目录
- **THEN** 目录不存在（或为空，`__init__.py` 删除）
- **AND** 表定义归 `server/tables/`（schema 层），业务方法归 `server/services/`（业务层）
- **AND** 无 `declarative_base()` 子类存在于代码库

#### Scenario: Row 兼容性不变

- **WHEN** 业务代码执行 `o = Orders.query_one(...); o.status = "57"; o.update()`
- **THEN** Row 的属性访问（`.status`）与无参 `update()` 行为与重写前一致
- **AND** 业务代码无需感知底层从字符串 SQL 改为 Core API

### Requirement: codegen 生成 Core Table 定义

`scripts/gen_tables.py` 重写为生成 `Table(..., Base.metadata, Column(...), ...)` 语句。
`#codegen:preserve-below` 标记段机制保护手写 `__table_args__` 约束不被覆盖。

#### Scenario: codegen 生成 Core Table

- **WHEN** `python scripts/gen_tables.py` 执行
- **THEN** 每个 `server/tables/<table>.py` 文件含 `__table__ = Table(...)` 定义
- **AND** MySQL 类型映射为 SQLAlchemy Column 类型（`varchar(n)` → `String(n)` 等）

#### Scenario: 手写约束保护

- **WHEN** codegen 重新生成 `tables/assets.py`（含手写 `CheckConstraint("id = 1")`）
- **THEN** `#codegen:preserve-below` 标记后的 `__table_args__` 内容不被覆盖
- **AND** 手写约束保留
