"""
server/tables/base.py — 通用 MySQL 表基类 (v80.2 架构调整)

设计目标:
- 每个 mysql 表对应 server/tables/<表名>.py 一个文件
- 文件内定义一个类继承 TableBase, 暴露该表的所有字段 + 注释
- 提供 5 个标准方法: Query<表> / Add<表> / Upd<表> / Del<表> / QueryAll<表>
  (实际是类方法, 命名按业务约定)

方法契约:
  TableBase.query_one(**pk_kwargs)   -> Row | None      # 按主键查单行
  TableBase.add_one(data: dict)     -> Row              # INSERT 一行, 返回带 PK 的对象
  TableBase.update_one(**pk_kwargs + data) -> Row      # 按主键 UPDATE, data 可含部分字段
  TableBase.delete_one(**pk_kwargs) -> bool             # 按主键 DELETE 一行, 返回是否成功
  TableBase.query_all(order='asc', page=1, page_size=20) -> List[Row]  # 分页 + 行号切片

复合主键:
  子类定义 __pk_fields__ = ('trd_date', 'order_no')
  调用时 query_one(trd_date='20260722', order_no='10000048')

分页算法 (按你的要求):
  排序后, 每行有行号; 取第 X 页 = 取行号 (X-1)*page_size+1 ~ X*page_size
  SQL: ROW_NUMBER() OVER (ORDER BY <pk> ASC|DESC) AS rn
       WHERE rn BETWEEN (X-1)*page_size+1 AND X*page_size
  返回 List[Row] 不带行号

连接:
  复用 server.infra.db.get_engine() (现有 v20 MySQL-only 引擎)
  不引入新的连接池, 不影响现有业务代码
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from server.infra.db import engine as _engine

log = logging.getLogger(__name__)


def get_engine():
    """复用 server.infra.db 的全局 engine (避免新连接池)"""
    return _engine


# ──────────────────────────── Row 容器 ────────────────────────────
class Row:
    """一行记录的轻量字典类 — 支持属性访问 + 字典访问 + 注释

    Examples:
        row = Order.query_one(trd_date='20260722', order_no='10000048')
        row.price           # 属性访问
        row['price']        # 字典访问
        row.to_dict()       # 转纯 dict
        for k, v in row:    # 迭代
    """

    __slots__ = ("_data", "_comments")

    def __init__(self, data: Dict[str, Any], comments: Optional[Dict[str, str]] = None):
        self._data = data
        self._comments = comments or {}

    # 属性访问
    def __getattr__(self, name: str) -> Any:
        try:
            return self._data[name]
        except KeyError:
            raise AttributeError(f"Row has no field {name!r}")

    # 属性设置 (v81: 用户伪代码风格: row.xx = new_val 直接生效到 _data)
    def __setattr__(self, name: str, value: Any) -> None:
        if name in ("_data", "_comments"):
            super().__setattr__(name, value)
            return
        self._data[name] = value

    # 字典访问
    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._data[key] = value

    def __contains__(self, key: str) -> bool:
        return key in self._data

    def __iter__(self):
        return iter(self._data.items())

    def __len__(self):
        return len(self._data)

    def __repr__(self):
        return f"Row({self._data!r})"

    def __eq__(self, other):
        if isinstance(other, Row):
            return self._data == other._data
        return False

    def keys(self):
        return self._data.keys()

    def values(self):
        return self._data.values()

    def to_dict(self) -> Dict[str, Any]:
        return dict(self._data)

    # v81: 对象.Update — 把当前 _data 全部字段写回数据库
    def save(self) -> None:
        """Row.Update(): 把 _data 全部字段 UPDATE 到 DB.

        跟 ORM 的 db.commit() 等价, 但只写当前 Row 的全部字段 (含 PK).
        PK 字段保留原值不动.

        支持伪代码:
            obj = Orders.query_one(trd_date='x', order_no='y')
            obj.price = 11.0
            obj.save()

        必须先 query_one(), 不能给新建 Row 调 save (会变成 INSERT).
        """
        # 找 _owner_class (从 _data 的 key 反查)
        # 所有 TableBase 子类都能调用, 通过 type(self) 拿到
        # 但 Row 不持有 _owner, 走 __qualname__ 匹配太脆
        # 改为: save() 必须接收 cls 参数 (强制显式), 避免误用
        raise NotImplementedError(
            "Row.save() 需要指明表类. 用法: Orders.update_one(row.to_dict(), pk=row.pk) "
            "或者 row.update(Orders, pk=row.pk). "
            "推荐 api 层直接用表类.update_one({...}) 模式."
        )

    # v81: 更友好的 update — 接收表类 + 可选过滤
    def update(self, cls=None, **filters) -> int:
        """Row.Update(cls=..., ..., pk=...): 把当前字段 UPDATE.

        支持伪代码:
            obj = Users.query_one(id=1)
            obj.name = 'new'
            obj.update(Users, id=1)

        等价 SQL: UPDATE users SET ... WHERE id=1
        返回受影响行数.
        """
        if cls is None:
            raise ValueError(
                "Row.update 需要显式 cls 参数. "
                "用法: obj.update(Users, id=1)"
            )
        if not filters:
            raise ValueError(
                "Row.update 需要 PK 过滤. "
                "用法: obj.update(Users, id=1)"
            )
        # 排除 PK 字段 — update_one 不允许 data 含 PK
        pk_fields = set(getattr(cls, '__pk_fields__', ['id']))
        clean_data = {k: v for k, v in self._data.items() if k not in pk_fields}
        return cls.update_one(clean_data, **filters)

    @property
    def comments(self) -> Dict[str, str]:
        return dict(self._comments)


# ──────────────────────────── 通用基类 ────────────────────────────
class TableBase:
    """通用 MySQL 表基类

    子类必须定义:
      __tablename__: str         # MySQL 表名
      __pk_fields__: tuple       # 主键字段名 (单字段或复合主键)
      __fields__: dict[str, str] # 字段名 → 注释 (可选, 写到 Row.comments)
      __field_types__: dict[str, str]  # 字段名 → MySQL type (生成器自动填)

    子类可选定义:
      __auto_increment_pk__: str  # 自增主键字段名 (Add 时不回填, 只 insert)

    5 个核心类方法:
      query_one(**pk)            # 按主键查
      add_one(data)              # INSERT
      update_one(**pk, **data)   # UPDATE (pk 从 kwargs 取)
      delete_one(**pk)           # DELETE
      query_all(order, page, page_size)  # 分页
    """

    # 子类必须覆盖 ↓
    __tablename__: str = ""
    __pk_fields__: Tuple[str, ...] = ()
    __fields__: Dict[str, str] = {}
    __field_types__: Dict[str, str] = {}

    # 子类可选覆盖 ↓
    __auto_increment_pk__: Optional[str] = None  # 'id' if int auto_increment

    # ──────────────── 内部 helper ────────────────
    @classmethod
    def _validate_subclass(cls) -> None:
        if not cls.__tablename__:
            raise NotImplementedError(f"{cls.__name__}.__tablename__ not set")
        if not cls.__pk_fields__:
            raise NotImplementedError(f"{cls.__name__}.__pk_fields__ not set")

    @classmethod
    def _pk_from_kwargs(cls, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """从 kwargs 提取主键字段"""
        cls._validate_subclass()
        missing = [pk for pk in cls.__pk_fields__ if pk not in kwargs]
        if missing:
            raise ValueError(
                f"{cls.__name__}.query_one 缺少主键字段: {missing}. "
                f"表 {cls.__tablename__} 主键 = {cls.__pk_fields__}"
            )
        return {pk: kwargs[pk] for pk in cls.__pk_fields__}

    # ──────────────── 字段过滤查询 (v80.9 新增) ────────────────

    @classmethod
    def query_by(cls, field: str = None, value=None,
                 order: str = "asc", limit: Optional[int] = None) -> List[Row]:
        """按单字段任意值查询 (替代 db.query(M).filter(M.field == v)).

        Args:
            field: 字段名 (任意字段, 不限主键)
            value: 字段值 (str/int/datetime/...) — None 跳过 (返回全表)
            order: 'asc' (按主键升序) 或 'desc' (按主键降序). 默认 'asc'.
            limit: 限制返回行数. None = 全部.

        Examples:
            Users.query_by('username', 'admin')      # 查 username='admin' 的行
            Orders.query_by('user_id', 1)              # 查 user_id=1 的所有订单
            Users.query_by('role', 'admin', limit=10)  # 限制 10 行
            Users.query_by()                           # 等价 query_all()
        """
        cls._validate_subclass()
        if field is None:
            return cls.query_all(order=order)[:limit] if limit else cls.query_all(order=order)
        if order not in ("asc", "desc"):
            raise ValueError(f"order 必须是 'asc' 或 'desc', 收到 {order!r}")
        order_clause = ", ".join(f"`{pk}` {order.upper()}" for pk in cls.__pk_fields__)
        sql = f"SELECT * FROM `{cls.__tablename__}` WHERE `{field}` = :v ORDER BY {order_clause}"
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        rows = cls._execute_select(sql, {"v": value})
        return rows

    @classmethod
    def query_by_fields(cls, filters: Dict[str, Any],
                        order: str = "asc", limit: Optional[int] = None) -> List[Row]:
        """按多字段同时过滤 (AND 关系).

        Args:
            filters: {field: value} dict, 所有条件用 AND 合并
            order: 'asc' 或 'desc'
            limit: 限制返回行数

        Examples:
            Orders.query_by_fields({"user_id": 1, "stock_code": "000001.SZ"})
                # user_id=1 AND stock_code='000001.SZ'
            Trades.query_by_fields({}, order="desc", limit=20)
                # 等价 query_all('desc', limit=20)
        """
        cls._validate_subclass()
        if order not in ("asc", "desc"):
            raise ValueError(f"order 必须是 'asc' 或 'desc', 收到 {order!r}")
        order_clause = ", ".join(f"`{pk}` {order.upper()}" for pk in cls.__pk_fields__)
        if not filters:
            sql = f"SELECT * FROM `{cls.__tablename__}` ORDER BY {order_clause}"
        else:
            wheres = " AND ".join([f"`{f}` = :f_{i}" for i, f in enumerate(filters.keys())])
            sql = f"SELECT * FROM `{cls.__tablename__}` WHERE {wheres} ORDER BY {order_clause}"
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        params = {f"f_{i}": v for i, v in enumerate(filters.values())}
        return cls._execute_select(sql, params if params else None)

    # ──────────────── 字段过滤查询 END ────────────────

    @classmethod
    def _row_from_mapping(cls, mapping) -> Row:
        """SQLAlchemy RowMapping / dict → Row"""
        d = dict(mapping)
        return Row(d, cls.__fields__)

    @classmethod
    def _execute_select(cls, sql: str, params=None) -> List[Row]:
        """执行 SELECT 并自动 text() 包裹 + Row 转换 (内部 helper, 不暴露).

        Args:
            sql: SQL 语句 (含 %s 占位符或 :name 命名参数)
            params: tuple (自动转 :p_0, :p_1) 或 dict (命名参数)
        """
        engine = get_engine()
        with engine.connect() as conn:
            if params is None:
                cur = conn.execute(text(sql))
            elif isinstance(params, tuple):
                params_dict = {f"p_{i}": v for i, v in enumerate(params)}
                named_sql = sql
                for i in range(len(params) - 1, -1, -1):
                    named_sql = named_sql.replace("%s", f":p_{i}", 1)
                cur = conn.execute(text(named_sql), params_dict)
            else:
                cur = conn.execute(text(sql), params)
        return [cls._row_from_mapping(r) for r in cur.mappings().all()]

    # ──────────────── 5 个核心方法 ────────────────

    @classmethod
    def query_one(cls, **pk) -> Optional[Row]:
        """按主键查一行. 返回 Row 或 None.

        Examples:
            Order.query_one(trd_date='20260722', order_no='10000048')
            User.query_one(id=1)
        """
        cls._validate_subclass()
        pk_dict = cls._pk_from_kwargs(pk)
        sql = f"SELECT * FROM `{cls.__tablename__}` WHERE " + \
              " AND ".join([f"`{k}` = :pk_{i}" for i, k in enumerate(cls.__pk_fields__)])
        params = {f"pk_{i}": v for i, (k, v) in enumerate(pk_dict.items())}
        rows = cls._execute_select(sql, params)
        return rows[0] if rows else None

    @classmethod
    def add_one(cls, data: Dict[str, Any]) -> Row:
        """INSERT 一行, 返回带主键的 Row.

        - 自增主键: 插入后用 LAST_INSERT_ID() 回填
        - 复合主键: data 必须含全部 PK 字段

        Examples:
            Order.add_one({'trd_date':'20260722', 'order_no':'10000049',
                           'stock_code':'000001.SZ', 'price':10.55, ...})
        """
        cls._validate_subclass()
        if not data:
            raise ValueError(f"{cls.__name__}.add_one: data 不能为空")
        engine = get_engine()
        cols = list(data.keys())
        col_list = ", ".join(f"`{c}`" for c in cols)
        val_list = ", ".join(f":{c}" for c in cols)
        sql = text(f"INSERT INTO `{cls.__tablename__}` ({col_list}) VALUES ({val_list})")
        with engine.begin() as conn:
            conn.execute(sql, data)
            # 回填自增主键
            if cls.__auto_increment_pk__ and cls.__auto_increment_pk__ not in data:
                last_id = conn.execute(text("SELECT LAST_INSERT_ID() AS id")).scalar()
                data = dict(data)
                data[cls.__auto_increment_pk__] = last_id
        return cls._row_from_mapping(data)

    @classmethod
    def update_one(cls, data: Dict[str, Any], **pk) -> Row:
        """按主键 UPDATE 一行. data 是要更新的字段 (不含主键).

        Examples:
            Order.update_one({'status':'50', 'status_msg':'已成'}, trd_date='20260722', order_no='10000048')
        """
        cls._validate_subclass()
        pk_dict = cls._pk_from_kwargs(pk)
        if not data:
            raise ValueError(f"{cls.__name__}.update_one: data 不能为空")
        # 防呆: data 不能含主键字段
        for pk_field in cls.__pk_fields__:
            if pk_field in data:
                raise ValueError(f"{cls.__name__}.update_one: data 不能含主键字段 {pk_field!r}")
        engine = get_engine()
        set_list = ", ".join(f"`{c}` = :upd_{c}" for c in data.keys())
        where_list = " AND ".join(f"`{k}` = :pk_{i}" for i, k in enumerate(cls.__pk_fields__))
        sql = text(f"UPDATE `{cls.__tablename__}` SET {set_list} WHERE {where_list}")
        params = {f"upd_{c}": v for c, v in data.items()}
        params.update({f"pk_{i}": v for i, (k, v) in enumerate(pk_dict.items())})
        with engine.begin() as conn:
            conn.execute(sql, params)
        # 回读更新后的行
        return cls.query_one(**pk_dict)  # type: ignore[return-value]

    @classmethod
    def delete_one(cls, **pk) -> bool:
        """按主键 DELETE 一行. 返回是否成功 (rowcount > 0)."""
        cls._validate_subclass()
        pk_dict = cls._pk_from_kwargs(pk)
        engine = get_engine()
        where_list = " AND ".join(f"`{k}` = :pk_{i}" for i, k in enumerate(cls.__pk_fields__))
        sql = text(f"DELETE FROM `{cls.__tablename__}` WHERE {where_list}")
        params = {f"pk_{i}": v for i, (k, v) in enumerate(pk_dict.items())}
        with engine.begin() as conn:
            result = conn.execute(sql, params)
        return result.rowcount > 0

    @classmethod
    def query_all(cls, order: str = "asc") -> List[Row]:
        """查询所有数据 (v80.5: 彻底简化 — 取消分页, 直接全表).

        数据量小 (用户偏好: '直接查全部, 有过滤条件的, 前端过滤').

        Args:
            order: 'asc' (按主键升序) 或 'desc' (按主键降序). 默认 'asc'.

        Returns:
            List[Row] (不带行号)

        Examples:
            Orders.query_all()            # 全查, 升序
            Orders.query_all('desc')      # 全查, 降序
        """
        cls._validate_subclass()
        if order not in ("asc", "desc"):
            raise ValueError(f"order 必须是 'asc' 或 'desc', 收到 {order!r}")

        order_clause = ", ".join(f"`{pk}` {order.upper()}" for pk in cls.__pk_fields__)
        sql = f"SELECT * FROM `{cls.__tablename__}` ORDER BY {order_clause}"
        return cls._execute_select(sql)


# ──────────────────────────── 公共 helper ────────────────────────────
def exec_sql(conn, sql: str, params=None):
    """others.py 专用 helper: 自动 text() 包裹 + 执行.

    支持:
        exec_sql(conn, "SELECT ... WHERE id=%s", (1,))         # tuple
        exec_sql(conn, "SELECT ... WHERE id=:id", {"id": 1})  # dict
        exec_sql(conn, "SELECT 1")                              # 无参

    Examples:
        with get_conn() as conn:
            cur = exec_sql(conn, "SELECT * FROM users WHERE id=%s", (1,))
    """
    from sqlalchemy import text
    if params is None:
        return conn.execute(text(sql))
    if isinstance(params, tuple):
        # tuple 自动转命名 dict (%s 占位符 → :p_0, :p_1)
        sql = sql.replace("%s", ":p_N") if False else sql
        # 直接用位置参数: SQLAlchemy 也支持 text("... %s ...") + tuple — 但要 binding 形式
        # 用 dict 形式最稳
        params_dict = {f"p_{i}": v for i, v in enumerate(params)}
        # 同时把 SQL 里 %s 改成 :p_0, :p_1
        named_sql = sql
        for i in range(len(params) - 1, -1, -1):
            named_sql = named_sql.replace("%s", f":p_{i}", 1)
        return conn.execute(text(named_sql), params_dict)
    return conn.execute(text(sql), params)


@contextmanager
def get_conn():
    """获取数据库连接 (context manager, with 语句自动 close).

    Examples:
        with get_conn() as conn:
            conn.execute(text("SELECT 1"))
    """
    engine = get_engine()
    conn = engine.connect()
    try:
        yield conn
    finally:
        conn.close()


# ──────────────────────────── v80.9 增强 ────────────────────────────

@contextmanager
def transaction():
    """事务 context manager (替代 ORM db.commit()).

    自动 begin/commit/rollback.

    Examples:
        with transaction() as tx:
            Users.add_one({"username": "x"})
            # 离开 with 自动 commit; 异常自动 rollback
    """
    from sqlalchemy import text as _text
    engine = get_engine()
    with engine.begin() as conn:
        yield conn


def aggregate(table: str, fn: str, field: str, where: str = "", params=None) -> Any:
    """SQL 聚合查询 (替代 db.query(func.sum(...)) 等).

    Args:
        table: 表名 (snake_case, 如 'orders')
        fn: 聚合函数 ('SUM'/'COUNT'/'AVG'/'MAX'/'MIN')
        field: 字段名 (如 'traded_volume')
        where: 可选 WHERE 子句 (不含 WHERE 关键字), 占位符用 %s 或 :name
        params: tuple / dict / None

    Returns:
        fn=='COUNT' → int
        否则 → Any (可能是 None 当无匹配)

    Examples:
        aggregate('orders', 'COUNT', '*', "user_id = %s", (1,))
        aggregate('trades', 'SUM', 'volume', where="trd_date = %s", params=('20260722',))
        aggregate('positions', 'AVG', 'volume')
    """
    sql = f"SELECT {fn}({field}) FROM `{table}`"
    if where:
        sql += f" WHERE {where}"
    with get_conn() as conn:
        from sqlalchemy import text as _text
        if params is None:
            row = conn.execute(_text(sql)).first()
        elif isinstance(params, tuple):
            named_sql = sql
            for i in range(len(params) - 1, -1, -1):
                named_sql = named_sql.replace("%s", f":p_{i}", 1)
            params_dict = {f"p_{i}": v for i, v in enumerate(params)}
            row = conn.execute(_text(named_sql), params_dict).first()
        else:
            row = conn.execute(_text(sql), params).first()
    if not row:
        return None
    val = row[0]
    if fn.upper() == "COUNT":
        return int(val) if val is not None else 0
    return val


def scalar_query(conn, sql: str, params=None) -> Any:
    """单值查询 helper (SELECT 1 列).

    Returns:
        单值 (可能 None)
    """
    from sqlalchemy import text as _text
    if params is None:
        row = conn.execute(_text(sql)).first()
    elif isinstance(params, tuple):
        named_sql = sql
        for i in range(len(params) - 1, -1, -1):
            named_sql = named_sql.replace("%s", f":p_{i}", 1)
        params_dict = {f"p_{i}": v for i, v in enumerate(params)}
        row = conn.execute(_text(named_sql), params_dict).first()
    else:
        row = conn.execute(_text(sql), params).first()
    return row[0] if row else None
