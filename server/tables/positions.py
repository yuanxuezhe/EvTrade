"""
server/tables/positions.py — 自动生成 (v80.2 tables-codegen skill)

表: `positions`  (8 字段, 主键: ['stock_code'])
描述: MySQL table `positions`

⚠️ 不要手动修改本文件 — 任何字段/主键变更请重新跑 scripts/gen_tables.py
   (skill: evtrade-table-codegen)
"""
from datetime import datetime
from server.tables.base import TableBase, Row
from typing import Any, ClassVar, Tuple


class Positions(TableBase):
    """MySQL table `positions`

    自动生成于 v80.2 架构调整, 继承 TableBase 获得 5 个标准方法:
      - query_one(**pk)            按主键查单行 → Row | None
      - add_one(data: dict)        INSERT 一行 → Row
      - update_one(data, **pk)     按主键 UPDATE → Row
      - delete_one(**pk)           按主键 DELETE → bool
      - query_all(order, page, page_size)  分页查询 → List[Row]

    主键: ['stock_code']
    """

    __tablename__: ClassVar[str] = 'positions'
    __pk_fields__: ClassVar[Tuple[str, ...]] = ('stock_code',)
    __auto_increment_pk__: ClassVar[str | None] = None

    __fields__: ClassVar[dict] = {
        'stock_code': '',
        'stock_name': '',
        'last_vol': '',
        'avl_vol': '',
        'vol': '',
        'cost_price': '',
        'synced_at': '',
        'synced_from': ''
    }

    __field_types__: ClassVar[dict] = {
        'stock_code': 'varchar(16)',
        'stock_name': 'varchar(64)',
        'last_vol': 'int',
        'avl_vol': 'int',
        'vol': 'int',
        'cost_price': 'float',
        'synced_at': 'datetime',
        'synced_from': 'varchar(16)'
    }

    # 字段 type hints (IDE 智能提示用, 运行时不影响行为)
    stock_code: str
    stock_name: str
    last_vol: int
    avl_vol: int
    vol: int
    cost_price: float
    synced_at: datetime
    synced_from: str
