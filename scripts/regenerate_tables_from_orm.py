#!/usr/bin/env python3
"""
A.2 辅助: 从 orm.py + strategy/models.py 的 declarative 类生成 Core Table 文件

不依赖 MySQL —— 直接遍历 declarative_base 子类, 生成对应 tables/<table>.py。
跳过已用新格式生成的 orders.py / trades.py (A.2 增量)。
"""
import os
import re
import sys
from pathlib import Path

# 把 server 目录加到 sys.path
os.environ.setdefault("EVTRADE_DB_URL", "mysql+pymysql://placeholder:placeholder@127.0.0.1:33066/evtrade?charset=utf8mb4")
TABLES_DIR = Path("server/tables")
ORM_FILES = ["server/models/orm.py", "server/services/strategy/models.py"]

TABLE_NAME_MAP = {
    # ORM 类名 → 表名 (codegen 一致)
    "Order": "orders",
    "Trade": "trades",
    "Position": "positions",
    "Asset": "assets",
    "SysStatus": "sys_status",
    "SysConfig": "sys_config",
    "ReconcileReport": "reconcile_report",
    "QuoteSnapshot": "quote_snapshots",
    "OrderNoSeq": "order_no_seq",
    "Stock": "stocks",
    "T0Task": "t0_tasks",
    "Strategy": "strategy",
    "StrategyRegime": "strategy_regime",
    "StrategyGrid": "strategy_grid",
    "StrategyAudit": "strategy_audit",
    "StrategyScript": "strategy_script",
    "StrategyTask": "strategy_task",
    "StrategyScriptAudit": "strategy_script_audit",
    "User": "users",
}


def mysql_to_sqlalchemy_type(type_str):
    """Type hint → SQLAlchemy Column 类型类名"""
    s = type_str.strip()
    if s in ("str", "string"):
        return "String"
    if s in ("int",):
        return "Integer"
    if s in ("float",):
        return "Float"
    if s in ("bool", "boolean"):
        return "Boolean"
    if s in ("datetime",):
        return "DateTime"
    if s in ("date",):
        return "Date"
    if s in ("time",):
        return "Time"
    if s in ("bytes", "bytea"):
        return "LargeBinary"
    if s in ("text", "Text"):
        return "Text"
    if s in ("Any", "any"):
        return "JSON"
    return "String"


def mysql_python_type(type_str):
    """type hint → Python 类型 hint"""
    s = type_str.strip()
    if s in ("str", "string"):
        return "str"
    if s in ("int",):
        return "int"
    if s in ("float",):
        return "float"
    if s in ("bool", "boolean"):
        return "bool"
    if s in ("datetime",):
        return "datetime"
    if s in ("date",):
        return "date"
    if s in ("time",):
        return "time"
    if s in ("bytes", "bytea"):
        return "bytes"
    if s in ("text", "Text"):
        return "str"
    if s in ("Any", "any"):
        return "Any"
    return "str"


def main():
    # 强制让 orm.py 加载, 然后抓所有 declarative 子类
    from sqlalchemy.orm import declarative_base
    from sqlalchemy import Column, Index, UniqueConstraint, CheckConstraint, Table
    from sqlalchemy.dialects import mysql as sa_mysql

    # 触发 import (会失败如果 EVTRADE_DB_URL 未设; 我们已经设了 placeholder)
    try:
        # 直接 import orm 文件, 绕过 server.tables/__init__.py 的 table 依赖
        import importlib.util
        def load_module(name, path):
            spec = importlib.util.spec_from_file_location(name, path)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[name] = mod
            spec.loader.exec_module(mod)
            return mod

        orm_module = load_module("server.models.orm_zz", "server/models/orm.py")
        strat_module = load_module("server.services.strategy.models_zz", "server/services/strategy/models.py")
        user_module = load_module("server.models.user_zz", "server/models/user.py")
    except Exception as e:
        print(f"⚠️ import 失败: {e}", file=sys.stderr)
        print("💡 需要先确保 EVTRADE_DB_URL 已设 (可 placeholder) + server/.env 已加载")
        return 1

    # 现在 sqlite-style Base 已是 declarative_base() 单例; 但 server.db 用了自己 Base
    # 如果 EVTRADE_DB_URL 没设真实 DB; 我们直接绕过 — 用 inspect 抓类属性
    import importlib

    # 收集所有 Base 子类
    candidates = []
    for mod_name in [orm_module, strat_module, user_module]:
        for attr_name in dir(mod_name):
            obj = getattr(mod_name, attr_name)
            if isinstance(obj, type) and hasattr(obj, "__tablename__"):
                candidates.append((attr_name, obj))

    print(f"🔍 发现 {len(candidates)} 个 declarative 类")

    # 写入策略
    skipped = {"orders", "trades"}  # A.2 已先写
    for cls_name, cls in candidates:
        table_name = getattr(cls, "__tablename__", None)
        if not table_name:
            continue
        if table_name in TABLE_NAME_MAP.values():
            # 找到对应的 PascalCase class name (与 codegen 一致)
            pass
        if table_name in skipped:
            print(f"⏭ 跳过 {table_name} (已生成)")
            continue

        # 读取 Column 字段
        from sqlalchemy import inspect
        mapper = inspect(cls)
        pk_cols = []
        col_lines = []
        annotation_lines = []
        imports = set()
        imports.add("from sqlalchemy import Table, Column, Index, CheckConstraint, UniqueConstraint, text")
        imports.add("from server.infra.db import Base")
        imports.add("from server.tables.base import TableBase, Row")
        imports.add("from typing import Any, ClassVar, Tuple")

        for col in mapper.columns:
            col_name = col.name
            col_type = col.type
            type_class = type(col_type).__name__
            # 特殊类型处理
            if type_class == "String":
                imports.add("from sqlalchemy import String")
                sa_type = f"String({col_type.length})"
            elif type_class == "Integer":
                imports.add("from sqlalchemy import Integer")
                sa_type = "Integer"
            elif type_class == "SmallInteger":
                imports.add("from sqlalchemy import SmallInteger")
                sa_type = "SmallInteger"
            elif type_class == "BigInteger":
                imports.add("from sqlalchemy import BigInteger")
                sa_type = "BigInteger"
            elif type_class == "Float":
                imports.add("from sqlalchemy import Float")
                sa_type = "Float"
            elif type_class == "Numeric":
                imports.add("from sqlalchemy import Numeric")
                if col_type.precision is not None and col_type.scale is not None:
                    sa_type = f"Numeric({col_type.precision}, {col_type.scale})"
                elif col_type.precision is not None:
                    sa_type = f"Numeric({col_type.precision})"
                else:
                    sa_type = "Numeric"
            elif type_class == "DateTime":
                imports.add("from sqlalchemy import DateTime")
                sa_type = "DateTime"
            elif type_class == "Date":
                imports.add("from sqlalchemy import Date")
                sa_type = "Date"
            elif type_class == "Time":
                imports.add("from sqlalchemy import Time")
                sa_type = "Time"
            elif type_class == "Text":
                imports.add("from sqlalchemy import Text")
                sa_type = "Text"
            # MySQL 方言类型 (mysql.LONGTEXT / MEDIUMTEXT / TINYTEXT / BIGINT / TINYINT / MEDIUMINT)
            # type() 返回类名不是父类 Text/BigInteger/Integer, 需单独映射, 否则兜底 String 触发
            # "VARCHAR requires a length on dialect mysql" DDL 错误.
            elif type_class in ("LONGTEXT", "MEDIUMTEXT", "TINYTEXT"):
                imports.add("from sqlalchemy import Text")
                sa_type = "Text"
            elif type_class == "BIGINT":
                imports.add("from sqlalchemy import BigInteger")
                sa_type = "BigInteger"
            elif type_class in ("TINYINT", "MEDIUMINT"):
                imports.add("from sqlalchemy import Integer")
                sa_type = "Integer"
            elif type_class == "LargeBinary":
                imports.add("from sqlalchemy import LargeBinary")
                sa_type = "LargeBinary"
            elif type_class == "Boolean":
                imports.add("from sqlalchemy import Boolean")
                sa_type = "Boolean"
            elif type_class == "JSON":
                imports.add("from sqlalchemy import JSON")
                sa_type = "JSON"
            else:
                # 兜底
                sa_type = "String"

            # 拼 Column 参数
            args = [repr(col_name), sa_type]
            if col.primary_key:
                args.append("primary_key=True")
                pk_cols.append(col_name)
            if not col.nullable and not col.primary_key:
                args.append("nullable=False")
            if col.default is not None and not col.primary_key:
                d = col.default
                if hasattr(d, "arg"):
                    arg = d.arg
                    # callable (如 _utcnow) → 保留 Python 端 default= (Core insert 时由 SA 注入),
                    # 不能转 server_default=text('CURRENT_TIMESTAMP') —— 实际 MySQL 列无 DEFAULT 时
                    # Core insert 省略该列会触发 "Field doesn't have a default value".
                    if callable(arg):
                        args.append("default=_utcnow")
                        imports.add("from server.utils.time import _utcnow")
                    elif isinstance(arg, str):
                        args.append(f"default={arg!r}")
                    elif isinstance(arg, (int, float, bool)):
                        args.append(f"default={arg!r}")
                    else:
                        # 复杂默认 → 留 Python callable 形式
                        args.append(f"default={arg!r}")
                elif hasattr(d, "for_update"):
                    args.append(f"server_default=text({str(d.for_update)!r})")
            # onupdate (如 updated_at 的 onupdate=_utcnow) —— 之前被整段丢失
            if col.onupdate is not None and hasattr(col.onupdate, "arg") and callable(col.onupdate.arg):
                args.append("onupdate=_utcnow")
                imports.add("from server.utils.time import _utcnow")
            if col.server_default is not None and not col.primary_key:
                sd = col.server_default
                if hasattr(sd, "arg"):
                    sd_arg = sd.arg
                    if isinstance(sd_arg, str):
                        args.append(f"server_default=text({sd_arg!r})")
            col_lines.append(f"        Column({', '.join(args)}),")

            # type hint
            py_type = {
                "String": "str",
                "Integer": "int",
                "SmallInteger": "int",
                "BigInteger": "int",
                "Float": "float",
                "Numeric": "float",
                "DateTime": "datetime",
                "Date": "date",
                "Time": "time",
                "Text": "str",
                "LargeBinary": "bytes",
                "Boolean": "bool",
                "JSON": "Any",
            }.get(type_class, "Any")
            if py_type == "datetime":
                imports.add("from datetime import datetime")
            elif py_type == "date":
                imports.add("from datetime import date")
            elif py_type == "time":
                imports.add("from datetime import time")
            elif py_type == "Any":
                imports.add("from typing import Any")
            annotation_lines.append(f"    {col_name}: {py_type}")

        # 读取 __table_args__ (Index / CheckConstraint / UniqueConstraint)
        table_args = getattr(cls, "__table_args__", None)
        index_lines = []
        if table_args:
            if isinstance(table_args, dict):
                items = table_args.get("constraints", [])
            else:
                items = list(table_args)
            for item in items:
                if isinstance(item, Index):
                    cols = [repr(c.name) for c in item.columns]
                    if item.unique:
                        index_lines.append(f"        Index({item.name!r}, {', '.join(cols)}, unique=True),")
                    else:
                        index_lines.append(f"        Index({item.name!r}, {', '.join(cols)}),")
                elif isinstance(item, CheckConstraint):
                    # sqltext 可能是 TextClause / Column / literal
                    sql_str = str(item.sqltext)
                    index_lines.append(f"        CheckConstraint({sql_str!r}, name={item.name!r}),")
                elif isinstance(item, UniqueConstraint):
                    cols = [repr(c.name) for c in item.columns]
                    index_lines.append(f"        UniqueConstraint({', '.join(cols)}, name={item.name!r}),")

        # 构造 class_name
        class_name = table_name_to_classname(table_name)
        pk_tuple = "(" + ", ".join(f"'{p}'" for p in pk_cols) + ")" if pk_cols else "()"
        if len(pk_cols) == 1:
            pk_tuple = f"('{pk_cols[0]}',)"
        # auto_inc
        auto_inc = next((c.name for c in mapper.columns if c.autoincrement), None)
        auto_inc_str = f"'{auto_inc}'" if auto_inc else "None"

        # 完整生成
        cols_str = "\n".join(col_lines)
        annotations_str = "\n".join(annotation_lines)
        args_str = "\n".join(index_lines) if index_lines else ""
        if args_str:
            table_args_str = f"""
    # codegen 读取 INFORMATION_SCHEMA.STATISTICS 生成的索引 / 约束
    __table_args__ = (
{args_str}
    )
    #codegen:preserve-below
    # 下方为手写 __table_args__ 扩展段 (Index / CheckConstraint / UniqueConstraint),
    # codegen 不会覆盖标记以下内容. 需重新生成时保留此标记.
"""
        else:
            table_args_str = """
    #codegen:preserve-below
    # 下方为手写 __table_args__ 扩展段 (Index / CheckConstraint / UniqueConstraint),
    # codegen 不会覆盖标记以下内容. 需重新生成时保留此标记.
"""

        # field dict
        fields_dict_lines = [f"        '{c.name}': ''" for c in mapper.columns]
        fields_dict_str = ",\n".join(fields_dict_lines)
        field_types_lines = [f"        '{c.name}': '{type(c.type).__name__.lower()}'" for c in mapper.columns]
        field_types_str = ",\n".join(field_types_lines)

        code = f'''"""
server/tables/{table_name}.py — 自动生成 (A.0 codegen Core Table 版)

表: `{table_name}`  ({len(mapper.columns)} 字段, 主键: {pk_cols})
描述: MySQL table `{table_name}`

⚠️ 不要手动修改本文件 (除 #codegen:preserve-below 标记以下的手写约束段) —
   任何字段/主键变更请重新跑 tables-codegen.
"""
{chr(10).join(sorted(imports))}


class {class_name}(TableBase):
    """MySQL table `{table_name}`

    自动生成，继承 TableBase 获得标准方法:
      - query_one(**pk)              按主键查单行 → Row | None
      - upsert_one(data, **pk)       INSERT OR UPDATE (统一写入入口)
      - delete_one(**pk)             按主键 DELETE → bool
      - query_all(order)             全表查询 → List[Row]
      - query_by(field, value)       单字段过滤
      - query_by_fields(filters)     多字段 AND 过滤

    主键: {pk_cols}
    """

    __tablename__: ClassVar[str] = '{table_name}'
    __pk_fields__: ClassVar[Tuple[str, ...]] = {pk_tuple}
    __auto_increment_pk__: ClassVar[str | None] = {auto_inc_str}

    __fields__: ClassVar[dict] = {{
{fields_dict_str}
    }}

    __field_types__: ClassVar[dict] = {{
{field_types_str}
    }}

    # 列定义 (SQLAlchemy Core Table): codegen 读 INFORMATION_SCHEMA.COLUMNS 生成
    __table__ = Table(
        '{table_name}', Base.metadata,
{cols_str}
        mysql_engine='InnoDB',
        mysql_charset='utf8mb4',
        extend_existing=True,
    ){table_args_str}

    # 字段 type hints (IDE 智能提示用, 运行时不影响行为)
{annotations_str}
'''
        out_path = TABLES_DIR / f"{table_name}.py"
        out_path.write_text(code, encoding="utf-8")
        print(f"  ✅ {out_path} ({len(code)} bytes)")

    print("🎉 A.2 增量生成完成")
    return 0


def table_name_to_classname(table_name):
    """snake_case → PascalCase"""
    parts = re.split(r"[_]", table_name)
    return "".join(p[:1].upper() + p[1:] for p in parts)


if __name__ == "__main__":
    sys.exit(main())
