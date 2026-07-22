"""
server/tables/stocks.py — 自动生成 (v80.2 tables-codegen skill)

表: `stocks`  (11 字段, 主键: ['stock_code'])
描述: MySQL table `stocks`

⚠️ 不要手动修改本文件 — 任何字段/主键变更请重新跑 scripts/gen_tables.py
   (skill: evtrade-table-codegen)
"""
from datetime import datetime
from server.tables.base import TableBase, Row
from typing import Any, ClassVar, Tuple


class Stocks(TableBase):
    """MySQL table `stocks`

    自动生成于 v80.2 架构调整, 继承 TableBase 获得 5 个标准方法:
      - query_one(**pk)            按主键查单行 → Row | None
      - add_one(data: dict)        INSERT 一行 → Row
      - update_one(data, **pk)     按主键 UPDATE → Row
      - delete_one(**pk)           按主键 DELETE → bool
      - query_all(order, page, page_size)  分页查询 → List[Row]

    主键: ['stock_code']
    """

    __tablename__: ClassVar[str] = 'stocks'
    __pk_fields__: ClassVar[Tuple[str, ...]] = ('stock_code',)
    __auto_increment_pk__: ClassVar[str | None] = None

    __fields__: ClassVar[dict] = {
        'stock_code': '',
        'stock_name': '',
        'sector': '',
        'is_t0_able': '',
        'min_buy_qty': '',
        'trade_unit': '',
        'short_name': '',
        'created_at': '',
        'updated_at': '',
        'stktype': '证券类型 0=股票 1=ETF',
        'scale': '价格小数位精度'
    }

    __field_types__: ClassVar[dict] = {
        'stock_code': 'varchar(16)',
        'stock_name': 'varchar(64)',
        'sector': 'varchar(64)',
        'is_t0_able': 'tinyint(1)',
        'min_buy_qty': 'int',
        'trade_unit': 'int',
        'short_name': 'varchar(16)',
        'created_at': 'datetime',
        'updated_at': 'datetime',
        'stktype': 'smallint',
        'scale': 'smallint'
    }

    # 字段 type hints (IDE 智能提示用, 运行时不影响行为)
    stock_code: str
    stock_name: str
    sector: str
    is_t0_able: bool
    min_buy_qty: int
    trade_unit: int
    short_name: str
    created_at: datetime
    updated_at: datetime
    stktype: int
    scale: int
