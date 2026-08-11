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
from datetime import datetime
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
    """一行记录的轻量字典类 — 支持属性访问 + 字典访问 + 注释 + 用户伪代码风格

    v81.11 增强:
    - __init__(**kw) 支持关键字实例化, 字段缺失用 __defaults__ 填默认
    - _owner_class 指向所属 TableBase 子类 (query_one 时绑定)
    - update() 无参调用: 自动用 _owner_class + self._data, WHERE PK + SET 全字段 (除 PK)

    Examples:
        # 旧用法 (v80 兼容)
        row = Order.query_one(trd_date='20260722', order_no='10000048')
        row.price = 11.0
        row.update(Orders, trd_date='20260722', order_no='10000048')  # 兼容

        # 新用法 (v81.11 用户伪代码)
        obj = Users(username='alice')           # 类实例化, 缺字段自动补默认
        Users.add_one(obj)                      # 接 Row
        obj = Users.query_one(id=1)
        obj.is_active = False
        obj.update()                            # 无参, 自动 PK WHERE + 全字段 SET
    """

    __slots__ = ("_data", "_comments", "_owner_class")

    def __init__(self, data=None, *, _owner_class=None, comments=None, **kw):
        """data dict 优先; kw 兼容; 双模式都支持"""
        # 1. 收集所有数据
        if isinstance(data, dict):
            base = dict(data)
        elif data is None:
            base = {}
        else:
            base = dict(data)
        base.update(kw)

        # 2. 自动填默认 (如果提供了 _owner_class, 用其 __defaults__)
        if _owner_class is not None:
            defaults = getattr(_owner_class, '__defaults__', {}) or {}
            for k, v in defaults.items():
                base.setdefault(k, v)

        # 3. _owner_class 不能进 data (避免 INSERT 时污染字段)
        self._owner_class = _owner_class
        self._data = base
        self._comments = comments or {}

    # v81.11: 无参 update (user-style pseudo code)
    def update(self, cls=None, **filters) -> int:
        """Row.update()  无参自动 PK WHERE + 全字段 SET (除 PK).

        支持伪代码 (用户原话):
            obj = Users.query_one(id=1)
            obj.is_active = False
            obj.update()                         # 自动 UPDATE users SET ALL WHERE id=1

        兼容老用法:
            obj.update(Users, id=1)

        返回受影响行数 (int).
        """
        # 模式 1: v81 兼容 - 显式 cls + filters
        if cls is not None:
            pk_fields = set(getattr(cls, '__pk_fields__', ['id']))
            clean_data = {k: v for k, v in self._data.items() if k not in pk_fields}
            n = cls.update_one(clean_data, return_rowcount=True, **filters)
            # update_one 默认返回 Row. 这里拿 rowcount.
            # 简化: 不调 update_one, 直接跑 UPDATE
        # 模式 2: v81.11 无参 - 用 self._owner_class
        owner = cls or self._owner_class
        if owner is None:
            raise ValueError(
                "Row.update() 无参需要 Row._owner_class (在 query_one/add_one 时自动绑定). "
                "或者显式调用: row.update(Users, id=1)"
            )
        pk_fields = set(owner.__pk_fields__)
        # WHERE 用 filters 或 self._data 的 PK
        if not filters:
            filters = {pk: self._data[pk] for pk in pk_fields if pk in self._data}
        missing_pk = [pk for pk in pk_fields if pk not in filters]
        if missing_pk:
            raise ValueError(
                f"Row.update() 缺少 PK 字段值: {missing_pk}. "
                f"必须先 query_one() 或显式 add_one() 后 update()."
            )
        # SET 用 self._data (除了 PK)
        clean_data = {k: v for k, v in self._data.items() if k not in pk_fields}
        # 直接跑 UPDATE, 拿 rowcount
        from sqlalchemy import text as _text
        from server.tables.base import get_engine as _engine
        set_list = ", ".join(f"`{c}` = :upd_{c}" for c in clean_data)
        where_list = " AND ".join(f"`{k}` = :pk_{i}" for i, k in enumerate(pk_fields))
        sql = _text(f"UPDATE `{owner.__tablename__}` SET {set_list} WHERE {where_list}")
        params = {f"upd_{c}": v for c, v in clean_data.items()}
        params.update({f"pk_{i}": v for i, (k, v) in enumerate(filters.items()) if k in pk_fields})
        with _engine().begin() as conn:
            res = conn.execute(sql, params)
        # 同步回 self._data (让 Row 真的反映 DB 状态)
        for k, v in filters.items():
            self._data[k] = v
        return res.rowcount

    # v81.11: Row.delete() 便捷 - 用 _owner_class + self PK
    def delete(self) -> bool:
        """Row.delete() 自动用 _owner_class + self PK DELETE.

        Examples:
            obj = Users.query_one(id=1)
            obj.delete()
        """
        owner = self._owner_class
        if owner is None:
            raise ValueError("Row.delete() 需要 _owner_class")
        pk_values = {pk: self._data[pk] for pk in owner.__pk_fields__ if pk in self._data}
        missing = [pk for pk in owner.__pk_fields__ if pk not in self._data]
        if missing:
            raise ValueError(f"Row.delete() 缺少 PK: {missing}")
        return owner.delete_one(**pk_values)

    # 属性访问
    def __getattr__(self, name: str) -> Any:
        try:
            return self._data[name]
        except KeyError:
            raise AttributeError(f"Row has no field {name!r}")

    # 属性设置 (v81: 用户伪代码风格: row.xx = new_val 直接生效到 _data)
    def __setattr__(self, name: str, value: Any) -> None:
        if name in ("_data", "_comments", "_owner_class"):
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

    # v81.11 老 update 已迁移到 L99 (无参自动 PK WHERE)

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
      __auto_increment_pk__: str     # 自增主键字段名 (Add 时不回填, 只 insert)
      __defaults__: dict             # v81.11: 字段默认值 (类实例化时填到 Row _data)

    5 个核心类方法:
      query_one(**pk)            # 按主键查, 返回 Row (绑定 _owner_class)
      add_one(data)              # INSERT (接 Row 或 dict)
      update_one(**pk, **data)   # UPDATE (pk 从 kwargs 取)
      delete_one(**pk)           # DELETE
      query_all(order, page, page_size)  # 分页

    v81.11: __call__(**kw) 工厂 — 显式实例化 Row 时自动用 __defaults__ 填字段
        Users(username='alice')                 # 等同 Row(_owner_class=Users, username='alice')
        Users.add_one(user_row)                 # 接 Row
        user_row.update()                       # 无参 WHERE PK + SET 全字段
    """

    # 子类必须覆盖
    __tablename__: str = ""
    __pk_fields__: Tuple[str, ...] = ()
    __fields__: Dict[str, str] = {}
    __field_types__: Dict[str, str] = {}

    # 子类可选覆盖
    __auto_increment_pk__: Optional[str] = None
    __defaults__: Dict[str, Any] = {}  # v81.11: 字段默认 (cls(**kw) 时填)

    # v81.11: __new__ 拦截类实例化 — Users(...) 自动返回 Row + 默认值
    def __new__(cls, *args, **kw):
        """类实例化 = 生成绑定到本类的 Row + 用 __defaults__ 填默认.

        3 种模式:
            obj = Users(username='alice')                 # kw 模式
            obj = Users({'username':'x'})                 # dict 模式 (兼容)
            obj = Users(username='alice', role='viewer')  # kw 模式 + 默认
        """
        if args and isinstance(args[0], dict):
            data = args[0]
            return Row(data, _owner_class=cls, **kw)
        return Row(_owner_class=cls, **kw)

    # ──────────────── 内部 helper ────────────────
    @classmethod
    def _validate_subclass(cls) -> None:
        if not cls.__tablename__:
            raise NotImplementedError(f"{cls.__name__}.__tablename__ not set")
        if not cls.__pk_fields__:
            raise NotImplementedError(f"{cls.__name__}.__pk_fields__ not set")

    # v81.10: 查 INFORMATION_SCHEMA 获取 NOT NULL 无 default 列 (cache 加速)
    _required_columns_cache = {}

    @classmethod
    def _get_required_columns(cls) -> list:
        if cls.__tablename__ in cls._required_columns_cache:
            return cls._required_columns_cache[cls.__tablename__]
        from server.db import engine
        sql = text(
            "SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t "
            "AND IS_NULLABLE = \'NO\' AND COLUMN_DEFAULT IS NULL"
        )
        with get_engine().connect() as conn:
            rows = conn.execute(sql, {"t": cls.__tablename__}).fetchall()
        result = [(r[0], (r[1] or "").lower()) for r in rows]
        cls._required_columns_cache[cls.__tablename__] = result
        return result

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
                        order: str = "asc", limit: Optional[int] = None,
                        columns: Optional[List[str]] = None) -> List[Row]:
        """按多字段同时过滤 (AND 关系).

        Args:
            filters: {field: value} dict, 所有条件用 AND 合并
            order: 'asc' 或 'desc'
            limit: 限制返回行数
            columns: 需返回的列白名单 (列表). None = SELECT * (全列).
                用于列表接口跳过大型 BLOB/JSON 列 (如 strategy_task.backtest_result),
                避免 SELECT * + ORDER BY 触发 MySQL 1038 (Out of sort memory)。

        Examples:
            Orders.query_by_fields({"user_id": 1, "stock_code": "000001.SZ"})
                # user_id=1 AND stock_code='000001.SZ'
            Trades.query_by_fields({}, order="desc", limit=20)
                # 等价 query_all('desc', limit=20)
            StrategyTask.query_by_fields(
                {"strategy_id": 1}, columns=["id", "status", "params"])
                # 只取轻量列, 不拖回 backtest_result 大 blob
        """
        cls._validate_subclass()
        if order not in ("asc", "desc"):
            raise ValueError(f"order 必须是 'asc' 或 'desc', 收到 {order!r}")
        order_clause = ", ".join(f"`{pk}` {order.upper()}" for pk in cls.__pk_fields__)
        if columns is not None:
            # 列名必须来自本表字段 (防注入 + 防拼错列名静默失败)
            bad = [c for c in columns if c not in cls.__fields__]
            if bad:
                raise ValueError(
                    f"{cls.__tablename__} 不存在列: {bad} (可选: {sorted(cls.__fields__)})"
                )
            if not columns:
                raise ValueError("columns 不能为空 list (需要全列请传 None)")
            select_cols = ", ".join(f"`{c}`" for c in columns)
        else:
            select_cols = "*"
        if not filters:
            sql = f"SELECT {select_cols} FROM `{cls.__tablename__}` ORDER BY {order_clause}"
        else:
            wheres = " AND ".join([f"`{f}` = :f_{i}" for i, f in enumerate(filters.keys())])
            sql = f"SELECT {select_cols} FROM `{cls.__tablename__}` WHERE {wheres} ORDER BY {order_clause}"
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        params = {f"f_{i}": v for i, v in enumerate(filters.values())}
        return cls._execute_select(sql, params if params else None)

    # ──────────────── 字段过滤查询 END ────────────────

    @classmethod
    def _row_from_mapping(cls, mapping) -> Row:
        """SQLAlchemy RowMapping / dict → Row (v81.11: 自动绑 _owner_class)"""
        d = dict(mapping)
        return Row(d, comments=cls.__fields__, _owner_class=cls)

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
    def add_one(cls, obj) -> Row:
        """INSERT 一行, 返回带完整数据 + PK 的 Row.

        v81.11: 接 Row 或 dict 两种模式:
            Row 模式: o = Users(username='x'); Users.add_one(o)
            dict 模式: Users.add_one({'username':'x'})    # 仍兼容

        PK 列 (主键 + AUTO_INCREMENT 列) 自动跳过, 让 DB 自动生成.

        Args:
            obj: Row 对象 或 dict
        Returns:
            Row (含全字段值 + 已生成 PK)
        """
        cls._validate_subclass()

        # v81.11: 接 Row / dict 双模式
        if isinstance(obj, Row):
            row = obj
            # 自动绑 owner (如果 Row 没绑)
            if row._owner_class is None:
                row._owner_class = cls
            # 转 dict
            data = dict(row._data)
        elif isinstance(obj, dict):
            data = dict(obj)
        else:
            raise TypeError(
                f"{cls.__name__}.add_one: obj 必须是 Row 或 dict, 收到 {type(obj).__name__}"
            )

        if not data:
            raise ValueError(f"{cls.__name__}.add_one: data 不能为空")

        # v81.11: PK 跳过 AUTO_INCREMENT (让 DB 生成), 复合 PK 字段保留
        # 跳过 Row 内部字段 (_owner_class/_data/_comments 这些不可能进 data, 但保险)
        data_out = {}
        for k, v in data.items():
            if k.startswith('_'):
                continue  # 内部字段
            if cls.__auto_increment_pk__ and k == cls.__auto_increment_pk__:
                continue  # AUTO_INCREMENT, 让 DB 生成
            data_out[k] = v

        # v81.10: 自动填充 NOT NULL 无 default 列 (MySQL strict mode)
        for col_name, col_type in cls._get_required_columns():
            if col_name not in data_out:
                if "datetime" in col_type or "timestamp" in col_type:
                    data_out[col_name] = datetime.now()
                elif "int" in col_type or "tinyint" in col_type:
                    data_out[col_name] = 0
                elif "float" in col_type or "double" in col_type or "decimal" in col_type or "numeric" in col_type:
                    data_out[col_name] = 0.0
                elif "varchar" in col_type or "char" in col_type or "text" in col_type:
                    data_out[col_name] = ""
                else:
                    data_out[col_name] = ""
        engine = get_engine()
        cols = list(data_out.keys())
        if not cols:
            raise ValueError(f"{cls.__name__}.add_one: 没有任何有效列可 INSERT")
        col_list = ", ".join(f"`{c}`" for c in cols)
        val_list = ", ".join(f":{c}" for c in cols)
        sql = text(f"INSERT INTO `{cls.__tablename__}` ({col_list}) VALUES ({val_list})")
        with engine.begin() as conn:
            conn.execute(sql, data_out)
            # v81.10: INSERT 后 SELECT * 回填完整 Row
            pk_dict = {k: data_out[k] for k in cls.__pk_fields__ if k in data_out}
            if len(pk_dict) == len(cls.__pk_fields__):
                sel_sql = "SELECT * FROM `" + cls.__tablename__ + "` WHERE " + \
                    " AND ".join([f"`{k}` = :pk_{i}" for i, k in enumerate(cls.__pk_fields__)])
                sel_params = {f"pk_{i}": v for i, (k, v) in enumerate(pk_dict.items())}
                row = conn.execute(text(sel_sql), sel_params).mappings().first()
                if row:
                    return cls._row_from_mapping(dict(row))
            # 兜底: AUTO_INCREMENT
            if cls.__auto_increment_pk__:
                last_id = conn.execute(text("SELECT LAST_INSERT_ID() AS id")).scalar()
                # v92 fix: SELECT * 回填完整 Row (nullable 字段如 t0_tasks.closed_at
                # 不会在 data_out 里, 直接返回会 AttributeError)
                sel_sql = (
                    "SELECT * FROM `" + cls.__tablename__ + "` WHERE `" +
                    cls.__auto_increment_pk__ + "` = :pk"
                )
                row = conn.execute(text(sel_sql), {"pk": last_id}).mappings().first()
                if row:
                    return cls._row_from_mapping(dict(row))
                data_out = dict(data_out)
                data_out[cls.__auto_increment_pk__] = last_id
        return cls._row_from_mapping(data_out)

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
    def update_by_fields(cls, data: Dict[str, Any], **filters) -> int:
        """按任意字段条件批量 UPDATE（非主键 WHERE）, 返回受影响行数。

        update_one 是主键 WHERE 单行; 这里支持多行批量更新 (如批次内全部 task 置状态)。

        Examples:
            StrategyTask.update_by_fields({'status': 'abandoned'}, strategy_id=1, batch_no=42)
        """
        cls._validate_subclass()
        if not data:
            raise ValueError(f"{cls.__name__}.update_by_fields: data 不能为空")
        if not filters:
            raise ValueError(f"{cls.__name__}.update_by_fields: 至少提供 1 个 WHERE 条件")
        # 防呆: data 不能含 WHERE 条件字段 (避免覆盖过滤条件)
        for f in filters:
            if f in data:
                raise ValueError(
                    f"{cls.__name__}.update_by_fields: 字段 {f!r} 不能同时在 data 和 filters"
                )
        engine = get_engine()
        set_list = ", ".join(f"`{c}` = :upd_{c}" for c in data.keys())
        where_list = " AND ".join(f"`{k}` = :f_{i}" for i, k in enumerate(filters))
        sql = text(f"UPDATE `{cls.__tablename__}` SET {set_list} WHERE {where_list}")
        params = {f"upd_{c}": v for c, v in data.items()}
        params.update({f"f_{i}": v for i, (k, v) in enumerate(filters.items())})
        with engine.begin() as conn:
            result = conn.execute(sql, params)
            return result.rowcount

    @classmethod
    def upsert_one(cls, data: Dict[str, Any], *, return_row: bool = False, **pk) -> Optional[Row]:
        """按主键 UPSERT 一行 (MySQL: INSERT ... ON DUPLICATE KEY UPDATE).

        v110 通用方法, 替代先 add_one 再 update_one 的两段写法 (rpc 同步资金等场景)。

        Args:
            data: 要写入的字段 (PK 列从 **pk 自动注入或 data 含 PK)
                  - 若 PK 在 data 里: 视作用户传入 (例 Assets.update_one({'id':1, 'cash':...}))
                  - 若 PK 在 **pk: 自动注入
            return_row: True 时回读一行返回 (默认 False - upsert 通常不关心回值)
            **pk: 主键字段作为关键字参数
                    复合 PK: upsert_one({'field':val}, trd_date='20260722', order_no='10000048')

        Returns:
            None 默认; return_row=True 时返回 Row 或 None
            行为: 1) PK 不存在 → INSERT; 2) PK 已存在 → UPDATE 该行 fields
            字段值与 data 完全一致 (UPSERT 是 id 维度的更新/插入)

        Examples:
            # 单 PK (Assets id=1 upsert 资金):
            Assets.upsert_one({'cash': x, 'available': x, ...}, id=1)
            # 复合 PK (trd_date + order_no):
            Orders.upsert_one({'status':'50'}, trd_date='20260722', order_no='10000048')
        """
        cls._validate_subclass()
        pk_dict = cls._pk_from_kwargs(pk) if pk else {}
        # 防呆: PK 不能两处都有 (避免 PK = data.PK vs **pk 谁优先困惑)
        if pk_dict:
            for pk_field in cls.__pk_fields__:
                if pk_field in data:
                    raise ValueError(
                        f"{cls.__name__}.upsert_one: PK 字段 {pk_field!r} 已从 **pk 传入, "
                        f"data 不应再含"
                    )
        else:
            # 从 data 拿 PK
            for pk_field in cls.__pk_fields__:
                if pk_field in data:
                    pk_dict[pk_field] = data[pk_field]
        if not pk_dict or set(pk_dict.keys()) != set(cls.__pk_fields__):
            raise ValueError(
                f"{cls.__name__}.upsert_one: 必须提供全部 PK ({cls.__pk_fields__!r}), 当前 {pk_dict}"
            )
        # 构造完整 data: 含 PK + user data
        full_data = dict(data)
        for k, v in pk_dict.items():
            full_data.setdefault(k, v)
        # 跳过 _ 内部字段
        out_data = {}
        # 如果是 UPSERT (pk_dict 已指定), 必须把 PK 列加进去, 否则 INSERT 时 MySQL
        # 会自增生成新 id, 导致 UPSERT 退化成 INSERT 新行 (而非 UPDATE 已有行)
        skip_auto_inc = not pk_dict
        for k, v in full_data.items():
            if k.startswith('_'):
                continue
            if skip_auto_inc and cls.__auto_increment_pk__ and k == cls.__auto_increment_pk__:
                continue
            out_data[k] = v
        # 自动填 NOT NULL 无 default 列 (与 add_one 同模式)
        for col_name, col_type in cls._get_required_columns():
            if col_name not in out_data:
                if "datetime" in col_type or "timestamp" in col_type:
                    out_data[col_name] = datetime.now()
                elif "int" in col_type or "tinyint" in col_type:
                    out_data[col_name] = 0
                elif "float" in col_type or "double" in col_type or "decimal" in col_type or "numeric" in col_type:
                    out_data[col_name] = 0.0
                elif "varchar" in col_type or "char" in col_type or "text" in col_type:
                    out_data[col_name] = ""
                else:
                    out_data[col_name] = ""
        if not out_data:
            raise ValueError(f"{cls.__name__}.upsert_one: 没有任何有效列可 UPSERT")
        engine = get_engine()
        cols = list(out_data.keys())
        col_list = ", ".join(f"`{c}`" for c in cols)
        placeholders = ", ".join(f":{c}" for c in cols)
        # ON DUPLICATE KEY UPDATE: 排除 PK 列 (PK 已经在 INSERT 里, 不能重复 SET)
        update_cols = [c for c in cols if c not in cls.__pk_fields__]
        if update_cols:
            update_list = ", ".join(f"`{c}` = VALUES(`{c}`)" for c in update_cols)
            sql = text(
                f"INSERT INTO `{cls.__tablename__}` ({col_list}) VALUES ({placeholders}) "
                f"ON DUPLICATE KEY UPDATE {update_list}"
            )
        else:
            # 全部列都是 PK (边界场景) — INSERT IGNORE
            sql = text(
                f"INSERT IGNORE INTO `{cls.__tablename__}` ({col_list}) VALUES ({placeholders})"
            )
        params = dict(out_data)
        with engine.begin() as conn:
            conn.execute(sql, params)
        if return_row:
            return cls.query_one(**pk_dict)
        return None

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
