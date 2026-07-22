"""
server/tables/trades.py — 自动生成 (v80.2 tables-codegen skill)

表: `trades`  (11 字段, 主键: ['trd_date', 'order_no', 'trade_id'])
描述: MySQL table `trades`

⚠️ 不要手动修改本文件 — 任何字段/主键变更请重新跑 scripts/gen_tables.py
   (skill: evtrade-table-codegen)
"""
from datetime import datetime
from server.tables.base import TableBase, Row
from typing import Any, ClassVar, Tuple


class Trades(TableBase):
    """MySQL table `trades`

    自动生成于 v80.2 架构调整, 继承 TableBase 获得 5 个标准方法:
      - query_one(**pk)            按主键查单行 → Row | None
      - add_one(data: dict)        INSERT 一行 → Row
      - update_one(data, **pk)     按主键 UPDATE → Row
      - delete_one(**pk)           按主键 DELETE → bool
      - query_all(order, page, page_size)  分页查询 → List[Row]

    主键: ['trd_date', 'order_no', 'trade_id']
    """

    __tablename__: ClassVar[str] = 'trades'
    __pk_fields__: ClassVar[Tuple[str, ...]] = ('trd_date', 'order_no', 'trade_id')
    __auto_increment_pk__: ClassVar[str | None] = None

    __fields__: ClassVar[dict] = {
        'trd_date': '',
        'order_no': '',
        'trade_id': '',
        'stock_code': '',
        'order_type': '',
        'price': '',
        'volume': '',
        'amount': '',
        'trade_time': '',
        'trade_type': '',
        'created_at': ''
    }

    __field_types__: ClassVar[dict] = {
        'trd_date': 'varchar(8)',
        'order_no': 'varchar(8)',
        'trade_id': 'varchar(64)',
        'stock_code': 'varchar(16)',
        'order_type': 'varchar(2)',
        'price': 'float',
        'volume': 'int',
        'amount': 'float',
        'trade_time': 'varchar(23)',
        'trade_type': 'int',
        'created_at': 'datetime'
    }

    # 字段 type hints (IDE 智能提示用, 运行时不影响行为)
    trd_date: str
    order_no: str
    trade_id: str
    stock_code: str
    order_type: str
    price: float
    volume: int
    amount: float
    trade_time: str
    trade_type: int
    created_at: datetime
