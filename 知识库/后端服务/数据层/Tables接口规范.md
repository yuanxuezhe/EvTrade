# Tables接口规范

## 对应代码路径

- `server/tables/base.py`（TableBase / Row / 模块级 helper）
- `server/tables/__init__.py`（统一导出全部表类 + base 符号，自动生成勿手改）
- `MIGRATION_GUIDE.md`（ORM → tables 迁移指北）

## 功能概述

`server/tables/` 是数据层唯一入口：每个 MySQL 表一个文件、一个继承 TableBase 的类（`__tablename__` / `__pk_fields__` / `__fields__` / `__field_types__`），底层用参数化 SQL text() 复用 infra.db 全局 engine。**所有 API 严禁直接 ORM（db.query/.filter/.add/.commit）**，统一走下列接口。

## 文件清单
| 代码文件 | 作用 |
|----------|------|
| server/tables/base.py | TableBase 基类、Row 容器、transaction/aggregate/scalar_query/get_conn/exec_sql |
| server/tables/<表名>.py | 每表一个类（gen_tables.py 自动生成，含字段注释） |
| server/tables/__init__.py | 统一导出（Orders/Users/... + base 全部符号） |

## 核心实现

### Row 容器（属性 + 字典双访问）
- `Row(data=None, *, _owner_class=None, comments=None, **kw)`；`row.xx` / `row['xx']` 读写均落 `_data`；支持 `in`、`iter(items)`、`len`、`keys()/values()/to_dict()`。
- `row.update(cls=None, **filters) -> int`
  - 无参模式（推荐）：`obj = Users.query_one(id=1); obj.is_active=False; obj.update()` —— 用 `_owner_class` 的 PK 从 `_data` 取 WHERE，SET 全部非 PK 字段，返回 rowcount。缺 PK 值抛 ValueError（须先 query_one/add_one）。
  - 兼容模式：`obj.update(Users, id=1)`。替代 ORM `m.x=val; db.commit()`。
- `row.delete() -> bool`：用 `_owner_class` + 自身 PK 调 delete_one。替代 `db.delete(m); db.commit()`。
- `row.save()`：**NotImplementedError**，勿用；改用 `TableCls.update_one(...)` 或 `row.update(cls, pk=...)`。

### TableBase 类方法（查询）

- `query_one(**pk) -> Row | None` —— 按主键查单行，绑定 `_owner_class`（Row 可直接 .update()/.delete()）。缺 PK 字段抛 ValueError。
  替代：`db.query(M).filter_by(pk=v).first()` / `db.query(M).get(pk)`。
  例：`Orders.query_one(trd_date='20260722', order_no='10000048')`（复合 PK）。
- `query_by(field=None, value=None, order='asc', limit=None) -> List[Row]` —— 单字段等值查（任意字段），value=None 退化为 query_all（可截 limit）。
  替代：`db.query(M).filter(M.field == v).all()`。例：`Users.query_by('username','admin', limit=10)`。
- `query_by_fields(filters: Dict, order='asc', limit=None, columns: List[str]|None=None) -> List[Row]` —— 多字段 AND 过滤；`columns` 列白名单（防注入，列名必须在 `__fields__`；用于跳过 backtest_result 等大 JSON 列防 MySQL 1038 排序内存溢出）；filters 为空等价 query_all + limit。
  替代：`db.query(M).filter(M.f1==v1, M.f2==v2).all()`。
- `query_by_in(field, values, order='asc', limit=None) -> List[Row]` —— 单字段 IN 批查（字段名先校验存在；空列表直接返回 [] 不发 SQL）。替代 `.filter(M.field.in_(values))`；批量场景必用（避免 N 次 round-trip）。
- `query_all(order='asc') -> List[Row]` —— 全表按 PK 升/降序（不分页，过滤交给前端）。替代 `db.query(M).all()`。

### TableBase 类方法（写入）

- `add_one(obj: Row | dict) -> Row` —— INSERT 一行，返回 SELECT * 回填的完整 Row（含 DB 生成字段）。
  - 自动跳过 `__auto_increment_pk__` 列与 `_` 开头内部字段；NOT NULL 无 default 列按类型自动补默认值（datetime→now、int→0、float→0.0、varchar→''，`_get_required_columns()` 查 INFORMATION_SCHEMA 并按表缓存）。
  - 替代：`db.add(m); db.commit(); db.refresh(m)`。例：`Users.add_one({'username':'x'})` 或 `Users.add_one(Users(username='x'))`。
- `update_one(data: Dict, **pk) -> Row` —— 按主键 UPDATE（data 不得含主键字段，防呆抛错），回读返回更新后 Row。
  替代：`db.query(M).filter_by(pk=v).update({...}); db.commit()`。例：`Orders.update_one({'status':'50'}, trd_date='x', order_no='y')`。
- `update_by_fields(data: Dict, **filters) -> int` —— 非主键 WHERE 批量 UPDATE，返回 rowcount；data 与 filters 不得有同名字段；filters 至少 1 个条件。
  例：`StrategyTask.update_by_fields({'status':'abandoned'}, strategy_id=1, batch_no=42)`。
- `upsert_one(data: Dict, *, return_row=False, **pk) -> Row | None` —— MySQL `INSERT ... ON DUPLICATE KEY UPDATE`；PK 必须齐全（`**pk` 或 data 提供，两处同时给抛错）；全 PK 边界走 INSERT IGNORE；同样自动补 NOT NULL 默认。替代"先 add 再 update"两段写（资金同步场景）。
- `delete_one(**pk) -> bool` —— 按主键 DELETE，rowcount>0 即 True。替代 `db.delete(m); db.commit()`。

### 子类声明约定
```python
class Orders(TableBase):
    __tablename__ = 'orders'
    __pk_fields__ = ('trd_date', 'order_no')   # 复合主键
    __auto_increment_pk__ = None               # 自增 PK 名（add 时不传）
    __fields__ = {...}                          # 字段名 → 中文注释（columns 白名单校验依据）
    __field_types__ = {...}                     # 字段名 → MySQL 类型
    __defaults__ = {}                           # 类实例化默认值
```
`__new__` 工厂：`Users(username='alice')` 直接返回绑定了 owner 的 Row（缺字段自动补 `__defaults__`）。

### 模块级 helper（复杂场景）
- `transaction() -> ContextManager[conn]`：`with transaction() as tx:` 内自动 begin/commit/rollback；替代 ORM 事务。tx 是底层 Connection，可配 `exec_sql` 用。
- `aggregate(table: str, fn: str, field: str, where='', params=None) -> Any`：聚合查询，fn ∈ SUM/COUNT/AVG/MAX/MIN；COUNT 返回 int，其余可能 None；where 不含 WHERE 关键字，占位符 `%s`（tuple）或 `:name`（dict）。
  替代：`db.query(func.sum(...))`。例：`aggregate('orders','COUNT','*',"user_id = %s",(1,))`。
- `scalar_query(conn, sql, params=None) -> Any`：单值查询（SELECT 1 列），须在 `get_conn()`/`transaction()` 的 conn 上执行。
- `get_conn() -> ContextManager[Connection]`：手写 SQL 的连接上下文。
- `exec_sql(conn, sql, params=None)`：自动 text() 包裹执行，支持 tuple（`%s` 自动转 `:p_N`）/ dict / 无参。
- `get_engine()`：复用 infra.db 全局 engine（不新建连接池）。

### ORM → tables 替换对照（MIGRATION_GUIDE.md 全量）
| ORM 写法 | tables 替代 |
|----------|-----------|
| db.query(M).filter_by(pk=v).first() | M.query_one(pk=v) |
| db.query(M).filter(M.field == v).all() | M.query_by('field', v) |
| db.query(M).filter(M.f1==v1, M.f2==v2).all() | M.query_by_fields({f1:v1, f2:v2}) |
| .filter(M.f.in_(list)) | M.query_by_in('f', list) |
| m.x = val; db.commit() | obj.x = val; obj.update() 或 M.update_one({...}, **pk) |
| db.add(m); db.commit(); db.refresh(m) | M.add_one(m_data)（直接返回完整 Row） |
| db.delete(m); db.commit() | M.delete_one(pk=v) 或 obj.delete() |
| db.query(func.sum(...)) | aggregate(table, 'SUM', field, where, params) |
| Depends(get_db) | 删（tables 用全局 engine） |
| db.refresh(obj) | 删（Row 即 dict） |
| obj.relations | query_by + 手动 join（前端做） |
| 聚合/子查询/跨表 JOIN | aggregate() / scalar_query() / 自写 SQL（transaction() 内） |

### 内部方法（勿直接调）
`_validate_subclass`（ tablename/pk 检查）、`_pk_from_kwargs`、`_get_required_columns`（INFORMATION_SCHEMA 缓存）、`_execute_select`（text() 执行 + Row 转换）、`_row_from_mapping`。

## 依赖关系
- 上游：api/*、services/*、repo/*（迁移后调用方）；rpc transport（延迟 import）
- 下游：server/infra/db.py 全局 engine；MySQL INFORMATION_SCHEMA

## 修改指南
- 新表：改 schema.yml → `python scripts/sync_schema.py apply`（生成 tables 代码），勿手写表文件。
- 需要新通用方法（如 query_by_in 式扩展）：加在 TableBase 并保持"参数化 SQL + 列名校验 + 返回 Row"三原则。
- 写入路径注意 NOT NULL 自动补默认仅在 add_one/upsert_one 生效；update_* 传空 data 抛 ValueError。
- 复合 PK 表 update_one 的 data 含 PK 字段会抛错——先 pop 掉再传。
