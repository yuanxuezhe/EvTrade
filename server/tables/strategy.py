"""
server/tables/strategy.py — 自动生成 (v80.2 tables-codegen skill)

表: `strategy`  (10 字段, 主键: ['id'])
描述: MySQL table `strategy`

⚠️ 不要手动修改本文件 — 任何字段/主键变更请重新跑 scripts/gen_tables.py
   (skill: evtrade-table-codegen)
"""
from datetime import datetime
from server.tables.base import TableBase, Row
from typing import Any, ClassVar, Tuple


class Strategy(TableBase):
    """MySQL table `strategy`

    自动生成于 v80.2 架构调整, 继承 TableBase 获得 5 个标准方法:
      - query_one(**pk)            按主键查单行 → Row | None
      - add_one(data: dict)        INSERT 一行 → Row
      - update_one(data, **pk)     按主键 UPDATE → Row
      - delete_one(**pk)           按主键 DELETE → bool
      - query_all(order, page, page_size)  分页查询 → List[Row]

    主键: ['id']
    """

    __tablename__: ClassVar[str] = 'strategy'
    __pk_fields__: ClassVar[Tuple[str, ...]] = ('id',)
    __auto_increment_pk__: ClassVar[str | None] = 'id'

    __fields__: ClassVar[dict] = {
        'id': '',
        'user_id': '',
        'stock_code': '',
        'type': '',
        'reference_price': '',
        'status': '',
        'base_volume': '',
        'note': '',
        'created_at': '',
        'updated_at': ''
    }

    __field_types__: ClassVar[dict] = {
        'id': 'int',
        'user_id': 'int',
        'stock_code': 'varchar(16)',
        'type': 'varchar(16)',
        'reference_price': 'float',
        'status': 'varchar(16)',
        'base_volume': 'int',
        'note': 'varchar(255)',
        'created_at': 'datetime',
        'updated_at': 'datetime'
    }

    # 字段 type hints (IDE 智能提示用, 运行时不影响行为)
    id: int
    user_id: int
    stock_code: str
    type: str
    reference_price: float
    status: str
    base_volume: int
    note: str
    created_at: datetime
    updated_at: datetime
