"""
server/tables/sys_status.py — 自动生成 (v80.2 tables-codegen skill)

表: `sys_status`  (11 字段, 主键: ['id'])
描述: MySQL table `sys_status`

⚠️ 不要手动修改本文件 — 任何字段/主键变更请重新跑 scripts/gen_tables.py
   (skill: evtrade-table-codegen)
"""
from datetime import datetime
from server.tables.base import TableBase, Row
from typing import Any, ClassVar, Tuple


class SysStatus(TableBase):
    """MySQL table `sys_status`

    自动生成于 v80.2 架构调整, 继承 TableBase 获得 5 个标准方法:
      - query_one(**pk)            按主键查单行 → Row | None
      - add_one(data: dict)        INSERT 一行 → Row
      - update_one(data, **pk)     按主键 UPDATE → Row
      - delete_one(**pk)           按主键 DELETE → bool
      - query_all(order, page, page_size)  分页查询 → List[Row]

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
