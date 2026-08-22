"""
server/tables/metadata.py — 从 tables/ 表类定义构建 SQLAlchemy metadata

背景: tables/ 层是纯数据类 (原生 SQL), 不持有 SQLAlchemy Table 对象。
alembic autogenerate 与 init_db() 的 create_all 需要 Base.metadata;
本模块在 import 时把 tables/ 各表类 (__tablename__/__pk_fields__/__fields__/
__field_types__/__auto_increment_pk__) 转成 sqlalchemy.Table 并注册进 Base.metadata,
让 tables/ 成为 schema 唯一来源 (orm.py 删除后仍可用)。

约定:
- users 表由 server/models/user.py 的 declarative User 单独注册 (避免双注册冲突),
  本模块跳过 users。
- 约束/索引信息 tables/ 未承载, 生成的 metadata 只含列/主键/自增;
  生产 DDL 以 alembic 静态基线迁移为准。
- 幂等: 已注册的表跳过 (支持 orm.py 与 tables/ 并存过渡期)。

用法:
    import server.tables           # 先加载表类
    import server.tables.metadata  # 触发注册到 Base.metadata
"""
from __future__ import annotations

import logging
import re

from sqlalchemy import (
    BigInteger, Boolean, Column, Date, DateTime, Float, Integer,
    JSON, LargeBinary, Numeric, String, Table, Text, Time,
)

from server.infra.db import Base
from server.tables.base import TableBase

log = logging.getLogger(__name__)

# users 由 server/models/user.py 的 declarative User 单独注册, 跳过避免双注册冲突
_SKIP_TABLES = {"users"}


def mysql_type_to_sa(mysql_type: str):
    """MySQL 类型字符串 → SQLAlchemy 类型 (与 gen_tables.py mysql_to_python 对齐)"""
    raw = (mysql_type or "text").strip().lower()
    base = re.split(r"[(]", raw)[0]
    args = re.findall(r"\((\d+)(?:,\s*(\d+))?\)", raw)

    if base in ("varchar", "char"):
        n = int(args[0][0]) if args else 255
        return String(n)
    if base == "decimal":
        p = int(args[0][0]) if args else 10
        s = int(args[0][1]) if args and args[0][1] else 0
        return Numeric(p, s)
    if raw == "tinyint(1)":
        return Boolean()
    if base in ("tinyint", "smallint", "mediumint", "int"):
        return Integer()
    if base == "bigint":
        return BigInteger()
    if base in ("float", "double"):
        return Float()
    if base in ("datetime", "timestamp"):
        return DateTime()
    if base == "date":
        return Date()
    if base == "time":
        return Time()
    if base in ("text", "mediumtext", "longtext"):
        return Text()
    if base == "json":
        return JSON()
    if base == "blob":
        return LargeBinary()
    return Text()


def register_tables_from_tables_module() -> int:
    """把 server.tables 下的所有 TableBase 子类注册进 Base.metadata (幂等)."""
    from server import tables as _tables

    registered = 0
    for name in dir(_tables):
        obj = getattr(_tables, name)
        if not (isinstance(obj, type) and issubclass(obj, TableBase) and obj is not TableBase):
            continue
        tablename = obj.__tablename__
        if not tablename or tablename in _SKIP_TABLES:
            continue
        if tablename in Base.metadata.tables:
            continue  # 已注册 (e.g. declarative) — 幂等跳过
        pk_fields = set(obj.__pk_fields__ or ())
        auto_inc = obj.__auto_increment_pk__
        columns = [
            Column(
                fname,
                mysql_type_to_sa((obj.__field_types__ or {}).get(fname)),
                primary_key=(fname in pk_fields),
                autoincrement=(auto_inc == fname),
                nullable=(fname not in pk_fields),
            )
            for fname in (obj.__fields__ or {})
        ]
        if not columns:
            continue
        Table(tablename, Base.metadata, *columns)
        registered += 1
    log.info("tables.metadata: registered %d tables into Base.metadata (skip users)", registered)
    return registered


register_tables_from_tables_module()
