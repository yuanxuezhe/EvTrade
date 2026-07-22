"""
server/tables/orders.py — 自动生成 (v80.2 tables-codegen skill)

表: `orders`  (23 字段, 主键: ['trd_date', 'order_no'])
描述: MySQL table `orders`

⚠️ 不要手动修改本文件 — 任何字段/主键变更请重新跑 scripts/gen_tables.py
   (skill: evtrade-table-codegen)
"""
from datetime import datetime
from server.tables.base import TableBase, Row
from typing import Any, ClassVar, Tuple


class Orders(TableBase):
    """MySQL table `orders`

    自动生成于 v80.2 架构调整, 继承 TableBase 获得 5 个标准方法:
      - query_one(**pk)            按主键查单行 → Row | None
      - add_one(data: dict)        INSERT 一行 → Row
      - update_one(data, **pk)     按主键 UPDATE → Row
      - delete_one(**pk)           按主键 DELETE → bool
      - query_all(order, page, page_size)  分页查询 → List[Row]

    主键: ['trd_date', 'order_no']
    """

    __tablename__: ClassVar[str] = 'orders'
    __pk_fields__: ClassVar[Tuple[str, ...]] = ('trd_date', 'order_no')
    __auto_increment_pk__: ClassVar[str | None] = None

    __fields__: ClassVar[dict] = {
        'trd_date': '',
        'order_no': '',
        'order_id': '',
        'user_def': '',
        'stock_code': '',
        'order_type': '',
        'price_type': '',
        'price': '',
        'volume': '',
        'traded_volume': '',
        'traded_amount': '',
        'avg_price': '',
        'cancelled_volume': '',
        'order_flag': '',
        'status': '',
        'status_msg': '',
        'order_time': '',
        'raw_id': '',
        'task_id': '',
        'strategy_type': '',
        'created_at': '',
        'updated_at': '',
        'pushed_at': ''
    }

    __field_types__: ClassVar[dict] = {
        'trd_date': 'varchar(8)',
        'order_no': 'varchar(8)',
        'order_id': 'varchar(64)',
        'user_def': 'varchar(255)',
        'stock_code': 'varchar(16)',
        'order_type': 'varchar(2)',
        'price_type': 'int',
        'price': 'float',
        'volume': 'int',
        'traded_volume': 'int',
        'traded_amount': 'float',
        'avg_price': 'float',
        'cancelled_volume': 'int',
        'order_flag': 'int',
        'status': 'varchar(2)',
        'status_msg': 'varchar(255)',
        'order_time': 'varchar(23)',
        'raw_id': 'varchar(8)',
        'task_id': 'int',
        'strategy_type': 'int',
        'created_at': 'datetime',
        'updated_at': 'datetime',
        'pushed_at': 'datetime'
    }

    # 字段 type hints (IDE 智能提示用, 运行时不影响行为)
    trd_date: str
    order_no: str
    order_id: str
    user_def: str
    stock_code: str
    order_type: str
    price_type: int
    price: float
    volume: int
    traded_volume: int
    traded_amount: float
    avg_price: float
    cancelled_volume: int
    order_flag: int
    status: str
    status_msg: str
    order_time: str
    raw_id: str
    task_id: int
    strategy_type: int
    created_at: datetime
    updated_at: datetime
    pushed_at: datetime
