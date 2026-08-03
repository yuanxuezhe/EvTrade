"""
server/tables/t0_tasks.py — 自动生成 (tables-codegen skill)

表: `t0_tasks`  (12 字段, 主键: ['id'])
描述: MySQL table `t0_tasks`

⚠️ 不要手动修改本文件 — 任何字段/主键变更请重新跑 tables-codegen
"""
from datetime import datetime
from server.tables.base import TableBase, Row
from typing import Any, ClassVar, Tuple


class T0Tasks(TableBase):
    """MySQL table `t0_tasks`

    自动生成，继承 TableBase 获得标准方法:
      - query_one(**pk)              按主键查单行 → Row | None
      - upsert_one(data, **pk)       INSERT OR UPDATE（统一写入入口）
      - delete_one(**pk)             按主键 DELETE → bool
      - query_all(order)             全表查询 → List[Row]
      - query_by(field, value)       单字段过滤
      - query_by_fields(filters)     多字段 AND 过滤

    主键: ['id']
    """

    __tablename__: ClassVar[str] = 't0_tasks'
    __pk_fields__: ClassVar[Tuple[str, ...]] = ('id',)
    __auto_increment_pk__: ClassVar[str | None] = 'id'

    __fields__: ClassVar[dict] = {
        'id': '',
        'user_id': '',
        'stock_code': '',
        'base_volume': '',
        'target_volume': '',
        'coefficient': '',
        'status': '',
        'note': '',
        'created_trd_date': '',
        'created_at': '',
        'updated_at': '',
        'closed_at': ''
    }

    __field_types__: ClassVar[dict] = {
        'id': 'int',
        'user_id': 'int',
        'stock_code': 'varchar(16)',
        'base_volume': 'int',
        'target_volume': 'int',
        'coefficient': 'float',
        'status': 'varchar(16)',
        'note': 'varchar(255)',
        'created_trd_date': 'varchar(8)',
        'created_at': 'datetime',
        'updated_at': 'datetime',
        'closed_at': 'datetime'
    }

    # 字段 type hints (IDE 智能提示用, 运行时不影响行为)
    id: int
    user_id: int
    stock_code: str
    base_volume: int
    target_volume: int
    coefficient: float
    status: str
    note: str
    created_trd_date: str
    created_at: datetime
    updated_at: datetime
    closed_at: datetime
