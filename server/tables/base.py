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

    @classmethod
    def _row_from_mapping(cls, mapping) -> Row:
        """SQLAlchemy RowMapping / dict → Row"""
        d = dict(mapping)
        return Row(d, cls.__fields__)

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
        engine = get_engine()
        sql = text(f"SELECT * FROM `{cls.__tablename__}` WHERE " +
                   " AND ".join([f"`{k}` = :pk_{i}" for i, k in enumerate(cls.__pk_fields__)]))
        params = {f"pk_{i}": v for i, (k, v) in enumerate(pk_dict.items())}
        with engine.connect() as conn:
            row = conn.execute(sql, params).mappings().first()
        return cls._row_from_mapping(row) if row else None

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
    def query_all(
        cls,
        order: str = "asc",
        page: int = 1,
        page_size: int = 20,
    ) -> List[Row]:
        """分页查询所有数据 (带行号切片).

        Args:
            order: 'asc' (按主键升序) 或 'desc' (按主键降序).
                   asc 时 ORDER BY pk1, pk2 ASC; desc 时 ORDER BY pk1, pk2 DESC.
            page: 第几页 (从 1 开始)
            page_size: 每页行数

        Returns:
            List[Row] (不带行号)

        算法:
            按主键排序, 给每行加行号 rn = ROW_NUMBER() OVER (ORDER BY pk)
            取 rn BETWEEN (page-1)*page_size+1 AND page*page_size
        """
        cls._validate_subclass()
        if order not in ("asc", "desc"):
            raise ValueError(f"order 必须是 'asc' 或 'desc', 收到 {order!r}")
        if page < 1:
            raise ValueError(f"page 必须 >= 1, 收到 {page}")
        if page_size < 1:
            raise ValueError(f"page_size 必须 >= 1, 收到 {page_size}")

        order_clause = ", ".join(f"`{pk}` {order.upper()}" for pk in cls.__pk_fields__)
        start_row = (page - 1) * page_size + 1
        end_row = page * page_size

        engine = get_engine()
        sql = text(f"""
            SELECT * FROM (
                SELECT *, ROW_NUMBER() OVER (ORDER BY {order_clause}) AS rn
                FROM `{cls.__tablename__}`
            ) AS _t
            WHERE rn BETWEEN :start AND :end
            ORDER BY rn ASC
        """)
        with engine.connect() as conn:
            rows = conn.execute(sql, {"start": start_row, "end": end_row}).mappings().all()
        return [cls._row_from_mapping(r) for r in rows]


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
