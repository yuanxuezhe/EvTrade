"""
server/tables/_applied_migrations.py — 自动生成 (tables-codegen skill)

表: `_applied_migrations`  (2 字段, 主键: ['name'])
描述: MySQL table `_applied_migrations`

⚠️ 不要手动修改本文件 — 任何字段/主键变更请重新跑 tables-codegen
"""
from datetime import datetime
from server.tables.base import TableBase, Row
from typing import Any, ClassVar, Tuple


class AppliedMigrations(TableBase):
    """MySQL table `_applied_migrations`

    自动生成，继承 TableBase 获得标准方法:
      - query_one(**pk)              按主键查单行 → Row | None
      - upsert_one(data, **pk)       INSERT OR UPDATE（统一写入入口）
      - delete_one(**pk)             按主键 DELETE → bool
      - query_all(order)             全表查询 → List[Row]
      - query_by(field, value)       单字段过滤
      - query_by_fields(filters)     多字段 AND 过滤

    主键: ['name']
    """

    __tablename__: ClassVar[str] = '_applied_migrations'
    __pk_fields__: ClassVar[Tuple[str, ...]] = ('name',)
    __auto_increment_pk__: ClassVar[str | None] = None

    __fields__: ClassVar[dict] = {
        'name': '',
        'applied_at': ''
    }

    __field_types__: ClassVar[dict] = {
        'name': 'varchar(255)',
        'applied_at': 'datetime'
    }

    # 字段 type hints (IDE 智能提示用, 运行时不影响行为)
    name: str
    applied_at: datetime
