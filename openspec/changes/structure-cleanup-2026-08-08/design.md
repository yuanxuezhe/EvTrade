# Design — 数据访问层重写：Tables 改用 SQLAlchemy Core Table 注册 metadata

> 本 design 固化 A 组并入本 change 后的架构决策。
> 方案选择：**方案 1**（彻底删除 declarative ORM，tables/ 改用 Core Table 注册 metadata）。
> 用户已确认接受重写数据访问层引擎的工程量与 review 风险。

## 背景与决策

### 现状（双轨制）

EvTrade 后端同时存在两套数据访问范式：

```
┌─ orm.py (declarative ORM) ──────────────────┐  ┌─ tables/ (TableBase+Row) ──────────┐
│                                              │  │                                     │
│ class Order(Base):                           │  │ class Orders(TableBase):            │
│     __tablename__ = "orders"                 │  │     __tablename__ = "orders"        │
│     trd_date = Column(String(8), primary_key)│  │     __field_types__ = {             │
│     order_no = Column(String(8), primary_key)│  │         "trd_date": "varchar(8)",   │
│     status = Column(String(2), default="48") │  │         "order_no": "varchar(8)",   │
│     ...                                      │  │         ...                         │
│                                              │  │     }  # 字符串元数据, 非 SQL 对象  │
│ 用法:                                        │  │                                     │
│   db.query(Order).filter(...).all()          │  │ 用法:                                │
│   db.add(Order(trd_date=..., ...))           │  │   Orders.query_one(order_no=...)    │
│   db.commit()                                │  │   Orders.add_one(Row(...))           │
│                                              │  │   row.update()                       │
│ 注册: import 触发 Base.metadata 注册         │  │   (内部 text(sql) 字符串拼接)        │
│                                              │  │                                     │
│ 被用于: alembic autogenerate + init_db       │  │ 被用于: 业务代码读写                 │
│         + 16 个 ORM 类的业务调用方           │  │         (api/repo/services 大部分)   │
└──────────────────────────────────────────────┘  └─────────────────────────────────────┘
                    │                                           │
                    └──── Base.metadata 注册 ──┬── alembic ────┘
                                                 └── init_db() create_all()
                                                 ↑
                                    只有 orm.py 触发注册, tables/ 不注册
```

### 阻塞点

删 `orm.py` 后，`Base.metadata` 空——`alembic autogenerate` 和 `init_db()` 的
`Base.metadata.create_all()` 都失去表结构扫描源。

### 方案选择：方案 1（彻底 Core Table）

**决策**：让 `tables/` 自己成为 metadata 的真源，`orm.py` 整个删除。

#### 三方案对比（explore 阶段评估）

| 维度 | 方案1: tables 改 Core Table | 方案2: orm.py 降级为 schema 壳 | 方案3: 新建 schema/registry |
|------|------------------------------|----------------------------------|------------------------------|
| 删 orm.py | ✅ 彻底删 | ❌ 保留作壳 | ✅ 删 |
| tables 持有 SQL 对象 | ✅ 是 | ❌ 否（仍字符串元数据） | ✅ 是 |
| codegen 重写 | ✅ 必须重写 | ❌ 不动 | ✅ 必须重写 |
| TableBase 重写 | ✅ 全部重写 | ❌ 不动 | ✅ 全部重写 |
| 业务代码迁移 | ✅ 16 类全部迁 | 🟡 部分（仅迁调用方，壳留下） | ✅ 16 类全部迁 |
| 双轨制消除 | ✅ 完全消除 | ❌ 残留壳 | ✅ 完全消除 |
| 工程量 | 🔴 最大 | 🟢 最小 | 🔴 大 |
| 「不改逻辑」约束 | ❌ 破坏（引擎重写） | ✅ 符合 | ❌ 破坏（引擎重写） |

**用户决策**：选方案 1，接受工程量与「破坏不改逻辑约束」的代价，换取彻底消除双轨制。

## 目标架构

```
┌─ 重写后 ─────────────────────────────────────────────────────────────────┐
│                                                                          │
│  server/tables/base.py                                                   │
│  ┌──────────────────────────────────────────────────────────────────┐    │
│  │  class TableBase:                                                 │   │
│  │      __table__: sqlalchemy.Table  # Core Table 对象              │   │
│  │      __pk_fields__: tuple                                         │   │
│  │                                                                   │   │
│  │      query_one(**pk)  → Table.select().where(...) → Row          │   │
│  │      add_one(obj)     → Table.insert().values(...)                │   │
│  │      update_one(**pk, **data) → Table.update().where(...)         │   │
│  │      delete_one(**pk) → Table.delete().where(...)                 │   │
│  │      query_all(order) → Table.select().order_by(...)              │   │
│  │      upsert_one(...)  → MySQL INSERT ... ON DUPLICATE KEY UPDATE  │   │
│  └──────────────────────────────────────────────────────────────────┘    │
│                                                                          │
│  server/tables/orders.py (codegen 生成)                                  │
│  ┌──────────────────────────────────────────────────────────────────┐    │
│  │  from sqlalchemy import Column, String, Integer, Float, ...     │   │
│  │  from server.infra.db import Base                                 │   │
│  │                                                                   │   │
│  │  class Orders(TableBase):                                         │   │
│  │      __tablename__ = "orders"                                      │   │
│  │      __pk_fields__ = ("trd_date", "order_no")                     │   │
│  │      __table__ = Table(                                           │   │
│  │          "orders", Base.metadata,                                 │   │
│  │          Column("trd_date", String(8), primary_key=True),         │   │
│  │          Column("order_no", String(8), primary_key=True),         │   │
│  │          Column("status", String(2), default="48"),               │   │
│  │          ...                                                       │   │
│  │          mysql_engine="InnoDB", mysql_charset="utf8mb4",           │   │
│  │      )                                                             │   │
│  │      # type hints 保留供 IDE                                       │   │
│  │      trd_date: str; order_no: str; ...                            │   │
│  └──────────────────────────────────────────────────────────────────┘    │
│                                                                          │
│  server/infra/db.py                                                      │
│  ┌──────────────────────────────────────────────────────────────────┐    │
│  │  Base = declarative_base()  # 仍提供 metadata 容器               │   │
│  │                                                                   │   │
│  │  def init_db():                                                  │   │
│  │      import server.tables  # 触发所有 Table 注册到 Base.metadata  │   │
│  │      Base.metadata.create_all(bind=admin_engine)                 │   │
│  └──────────────────────────────────────────────────────────────────┘    │
│                                                                          │
│  server/alembic/env.py                                                   │
│  ┌──────────────────────────────────────────────────────────────────┐    │
│  │  import server.tables  # noqa  # 触发 Table 注册                 │   │
│  │  from server.infra.db import Base                                 │   │
│  │  target_metadata = Base.metadata                                   │   │
│  └──────────────────────────────────────────────────────────────────┘    │
│                                                                          │
│  ❌ server/models/orm.py  — 删除                                         │
│  ❌ server/services/strategy/models.py — 删除（7 个 strategy ORM 类）    │
│  ❌ server/db.py — 删除（B 组，垫片）                                    │
└──────────────────────────────────────────────────────────────────────────┘
```

## 关键设计决策

### D1: `declarative_base()` 保留还是删？

**保留** `Base = declarative_base()` 在 `server/infra/db.py`。

理由：`Base.metadata` 是 SQLAlchemy 的 metadata 容器，Core `Table(..., Base.metadata, ...)`
需要它作为注册目标。删了 `declarative_base()` 就要手动建 `MetaData()` 实例——多此一举。
`Base` 这个对象**不再被任何业务类继承**（declarative ORM 类全删），只作为 metadata 容器存在。

### D2: codegen 生成器如何改写？

`scripts/gen_tables.py` 现在读 `INFORMATION_SCHEMA` 生成字符串元数据类。改写为生成
`Table(..., Base.metadata, Column(...), ...)` 语句。

**关键映射**：MySQL 类型 → SQLAlchemy Column 类型

| MySQL | SQLAlchemy |
|-------|------------|
| `varchar(n)` | `String(n)` |
| `int` / `bigint` | `Integer` / `BigInteger` |
| `tinyint(1)` | `Boolean` |
| `float` / `double` | `Float` |
| `decimal(p,s)` | `Numeric(p, s)` |
| `datetime` / `timestamp` | `DateTime` |
| `text` / `mediumtext` / `longtext` | `Text` |

**默认值**：`Column(..., default=X)` 或 `server_default=text("...")`——codegen 从
`INFORMATION_SCHEMA.COLUMNS.COLUMN_DEFAULT` 读取并生成。

**主键**：`INFORMATION_SCHEMA.KEY_COLUMN_USAGE` 查 PK，对应 `primary_key=True`。

**索引/约束**：`orm.py` 现有 `__table_args__` 里的 `Index(...)` / `CheckConstraint(...)` /
`UniqueConstraint(...)` 需要 codegen 也能生成——但 `INFORMATION_SCHEMA.STATISTICS` 只能读
索引，`CheckConstraint`（如 `ck_asset_single_row`）是业务约束，codegen 读不到。

**决策**：codegen 生成基础 `Table(...)` + PK + 索引；**手动维护的约束**（如
`CheckConstraint("id = 1")`）在生成文件里用 `__table_args__` 补充，codegen 不覆盖该属性
（类似现在 codegen 保留手写扩展的模式）。具体实现：codegen 生成 `__table__ = Table(...)`
+ `__table_args__ = (...)` 手动约束段，codegen 检测到 `__table_args__` 存在则跳过覆盖。

### D3: `TableBase` 方法重写策略

**现状**：`TableBase` 用 `text(sql)` 字符串拼接执行所有操作（L139-147 的 UPDATE 拼接、
L432-445 的 SELECT 拼接等）。

**重写后**：用 `Table` 对象的 Core API：

```python
# query_one
stmt = cls.__table__.select().where(
    *(cls.__table__.c[pk] == v for pk, v in pk_dict.items())
)
with engine.connect() as conn:
    result = conn.execute(stmt)
    row = result.mappings().first()
return cls._row_from_mapping(row) if row else None

# add_one
stmt = cls.__table__.insert().values(data)
with engine.begin() as conn:
    result = conn.execute(stmt)
    # 拿自增 PK（如果有）

# update_one
stmt = cls.__table__.update().where(
    *(cls.__table__.c[pk] == v for pk, v in pk_dict.items())
).values(**clean_data)
with engine.begin() as conn:
    result = conn.execute(stmt)

# delete_one
stmt = cls.__table__.delete().where(
    *(cls.__table__.c[pk] == v for pk, v in pk_dict.items())
)

# query_all
stmt = cls.__table__.select()
if order == "desc":
    pk = cls.__pk_fields__[0]
    stmt = stmt.order_by(cls.__table__.c[pk].desc())
```

**`Row` 类不变**：它仍是轻量字典类，`__getattr__` 转发 `_data`，业务代码
（`o.status = "57"; o.update()`）形态不变。`_row_from_mapping` 从 `result.mappings().first()`
拿 dict 构造 Row。

**`aggregate` / `scalar_query` / `exec_sql`**：保留字符串 SQL 入口（复杂聚合 SQL 用 Core
表达式太繁琐），但内部可选用 `text()` 或 `select(func.count(...))`。优先保持兼容，能不改就不改。

### D4: `Row.update()` 无参模式如何实现？

现状 `Row.update()`（base.py L99-151）用 `text(f"UPDATE ... SET ... WHERE ...")` 字符串拼接。
重写后改用 `_owner_class.__table__.update().where(...).values(...)`。

**但有一个微妙问题**：`Row` 不持有对 `Table` 对象的强引用（避免循环），通过
`_owner_class` 间接拿到 `__table__`。这个模式保留。

### D5: `upsert_one` 的 MySQL `ON DUPLICATE KEY UPDATE`

现状 `upsert_one`（base.py L566）拼 `INSERT ... ON DUPLICATE KEY UPDATE` 字符串。
重写后用 SQLAlchemy 的 `from sqlalchemy.dialects.mysql import insert`：

```python
from sqlalchemy.dialects.mysql import insert as mysql_insert
stmt = mysql_insert(cls.__table__).values(data)
stmt = stmt.on_duplicate_key_update(**{k: stmt.inserted[k] for k in data})
```

这是 Core 的标准 upsert 模式，比字符串拼接更安全（自动转义）。

### D6: 16 个 ORM 类的业务代码迁移模式

每类的迁移模式统一：

| ORM 写法 | Tables 写法 |
|---------|-------------|
| `from server.models.orm import Order` | `from server.tables import Orders` |
| `db.query(Order).filter_by(order_no=x).first()` | `Orders.query_one(order_no=x)` |
| `db.query(Order).filter(Order.stock_code==x).all()` | `Orders.query_by(field="stock_code", value=x)` |
| `Order(trd_date=..., ...)` + `db.add(o)` | `Orders.add_one(Row(trd_date=..., ...))` 或 `Orders.upsert_one({...})` |
| `o.status = "57"; db.commit()` | `o.status = "57"; o.update()` |
| `db.query(Position).filter(...).delete()` | `Positions.delete_one(stock_code=...)` |
| `get_active_trd_date(db)` | `get_active_trd_date()`（已忽略 db 参数，删参数留兼容签名） |

**类型签名**：`List[Order]` → `List[Row]`（Row 兼容属性访问，调用方 `.status` 仍工作）。
若 IDE 报类型错，改 `List[Row]` 或 `List[Any]`。

### D7: `services/strategy/models.py` 7 个 strategy ORM 类

`Strategy / StrategyRegime / StrategyGrid / StrategyAudit / StrategyScript /
StrategyTask / StrategyScriptAudit` 这 7 个 ORM 类已在 `tables/` 有对应文件
（`tables/strategy.py`, `tables/strategy_grid.py` 等，codegen 已生成）。

迁移与 `orm.py` 的 9 个类同样模式。`services/strategy/models.py`（316 行）整文件删除。

**但**：`services/strategy/models.py` 里有 ORM 类的**业务方法**吗？需在迁移前确认——
若有（如 `Strategy.to_dict()`），迁到 `services/strategy/repository.py` 或对应 service 层。

### D8: `tables/__init__.py` 触发注册

`tables/__init__.py` 已 import 所有表类。重写后，import 这些类即触发 `Table(..., Base.metadata)`
注册。`alembic/env.py` 和 `init_db()` 只需 `import server.tables`（整包）即可全部注册。

### D9: codegen 重新生成会覆盖手写改动吗？

现状 codegen 文件头有 `⚠️ 不要手动修改本文件`。重写后仍保持：codegen 覆盖 `__table__`
定义，但 `__table_args__`（手动约束段）codegen 检测存在则保留。

**`orm.py` 里的 `Index(...)` / `CheckConstraint(...)` 需要先迁到 codegen 生成 + 手动 `__table_args__`**
这个是迁移中最易遗漏的点，tasks 里单列。

### D10: 迁移顺序与验证策略

按风险分级执行，每个 phase 可独立验证 + commit：

```
Phase 0: 重写 codegen + TableBase + 重新生成 19 文件
         （此阶段 tables/ 仍与 orm.py 并存，业务代码未动，可独立验证）
   验证: python scripts/gen_tables.py --dry-run 检查生成
         python -c "import server.tables; from server.infra.db import Base; print(Base.metadata.tables)"
         pytest server/tests/  全量通过（tables API 形态不变）

Phase 1: alembic/env.py + init_db() 改 import server.tables
         （此阶段 Base.metadata 来源切换，orm.py 仍在但不被注册源使用）
   验证: alembic revision --autogenerate -m "test" 生成空 diff（证明 metadata 一致）
         python -c "from server.infra.db import init_db; init_db()"  create_all 成功

Phase 2: 🟢 低风险业务代码迁移（SysStatus / QuoteSnapshot）
         guards.py / repo/system.py / quote_consumer.py
   验证: pytest server/tests/strategy/ + 手动 503 屏障测试

Phase 3: 🟡 中风险（Order / Trade 写路径）
         services/strategy/engine.py + t0/engine.py + api/admin/sys_status.py
   验证: pytest server/tests/strategy/test_engine.py
         + 下单 + 撤单端到端（scripts/e2e/test_orders_e2e.py）

Phase 4: 🟠 中高风险（类型签名 + 列表）
         services/t0/aggregators.py + pnl.py + core.py
   验证: pytest server/tests/  t0 相关全过

Phase 5: 🔴 高风险（reconcile Position/Asset 链式）
         services/reconcile.py
   验证: pytest server/tests/ + scripts/e2e/test_* + 手动日初对账

Phase 6: 删 orm.py + services/strategy/models.py + db.py(B组)
   验证: grep 确认零残留 import
         python -c "import server.main"  启动无报错

Phase 7: C 组（kb/ 删除）+ D 组（api/index.js 拆分）
   验证: 前端 build + 浏览器冒烟
```

## 风险与缓解

| 风险 | 缓解 |
|------|------|
| codegen 生成与 orm.py 现有 `__table_args__` 约束不一致 | Phase 0 用 `alembic revision --autogenerate` 生成空 diff 验证 metadata 等价 |
| `TableBase` 方法重写引入 SQL 语义差异（如 upsert 的 ODKU 行为） | 每个 phase 后跑 e2e + 对比改写前后执行的 SQL log |
| 16 个 ORM 类迁移遗漏调用点 | 每个 phase 后 `grep -rn "from server.models.orm\|from server.services.strategy.models"` 确认零残留 |
| `services/strategy/models.py` 有 ORM 业务方法 | Phase 6 前先 grep 类方法定义，有则迁到 repository |
| alembic 历史迁移脚本可能依赖 orm.py import | grep `server/migrations/*.py` 确认只 import `server.infra.db.engine`（已确认，见 explore 阶段） |
| codegen 重写后生成文件与手写 `__table_args__` 冲突 | codegen 加 `#codegen:preserve-below` 标记段，手写约束在标记后不被覆盖 |

## 不在本 design 范围

- 巨型文件拆分（strategy/service.py 999 行、T0Trade.vue 1232 行等）——另立 change
- 前端 DataTableView 迁移收口——另立 change
- evctl.py 784 行拆分——另立 change
