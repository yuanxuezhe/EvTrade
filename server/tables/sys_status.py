"""
server/tables/sys_status.py — 自动生成 (tables-codegen skill)

表: `sys_status`  (11 字段, 主键: ['id'])
描述: MySQL table `sys_status`

⚠️ 不要手动修改本文件 — 任何字段/主键变更请重新跑 tables-codegen
"""
from datetime import datetime
from server.tables.base import TableBase, Row
from typing import Any, ClassVar, Tuple


class SysStatus(TableBase):
    """MySQL table `sys_status`

    自动生成，继承 TableBase 获得标准方法:
      - query_one(**pk)              按主键查单行 → Row | None
      - upsert_one(data, **pk)       INSERT OR UPDATE（统一写入入口）
      - delete_one(**pk)             按主键 DELETE → bool
      - query_all(order)             全表查询 → List[Row]
      - query_by(field, value)       单字段过滤
      - query_by_fields(filters)     多字段 AND 过滤

    主键: ['id']
    """

    __tablename__: ClassVar[str] = 'sys_status'
    __pk_fields__: ClassVar[Tuple[str, ...]] = ('id',)
    __auto_increment_pk__: ClassVar[str | None] = None

    __fields__: ClassVar[dict] = {
        'id': '',
        'trd_date': '',
        'status': '',
        'is_half_day': '',
        'initialized_at': '',
        'initialized_by': '',
        'closed_at': '',
        'closed_by': '',
        'remark': '',
        'created_at': '',
        'updated_at': ''
    }

    __field_types__: ClassVar[dict] = {
        'id': 'int',
        'trd_date': 'varchar(8)',
        'status': 'varchar(16)',
        'is_half_day': 'int',
        'initialized_at': 'datetime',
        'initialized_by': 'int',
        'closed_at': 'datetime',
        'closed_by': 'int',
        'remark': 'varchar(255)',
        'created_at': 'datetime',
        'updated_at': 'datetime'
    }

    # 字段 type hints (IDE 智能提示用, 运行时不影响行为)
    id: int
    trd_date: str
    status: str
    is_half_day: int
    initialized_at: datetime
    initialized_by: int
    closed_at: datetime
    closed_by: int
    remark: str
    created_at: datetime
    updated_at: datetime
