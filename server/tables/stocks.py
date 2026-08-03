"""
server/tables/stocks.py — 自动生成 (tables-codegen skill)

表: `stocks`  (11 字段, 主键: ['stock_code'])
描述: MySQL table `stocks`

⚠️ 不要手动修改本文件 — 任何字段/主键变更请重新跑 tables-codegen
"""
from datetime import datetime
from server.tables.base import TableBase, Row
from typing import Any, ClassVar, Tuple


class Stocks(TableBase):
    """MySQL table `stocks`

    自动生成，继承 TableBase 获得标准方法:
      - query_one(**pk)              按主键查单行 → Row | None
      - upsert_one(data, **pk)       INSERT OR UPDATE（统一写入入口）
      - delete_one(**pk)             按主键 DELETE → bool
      - query_all(order)             全表查询 → List[Row]
      - query_by(field, value)       单字段过滤
      - query_by_fields(filters)     多字段 AND 过滤

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
        'stktype': '',
        'scale': '',
        'created_at': '',
        'updated_at': ''
    }

    __field_types__: ClassVar[dict] = {
        'stock_code': 'varchar(16)',
        'stock_name': 'varchar(64)',
        'sector': 'varchar(64)',
        'is_t0_able': 'tinyint(1)',
        'min_buy_qty': 'int',
        'trade_unit': 'int',
        'short_name': 'varchar(16)',
        'stktype': 'smallint',
        'scale': 'smallint',
        'created_at': 'datetime',
        'updated_at': 'datetime'
    }

    # 字段 type hints (IDE 智能提示用, 运行时不影响行为)
    stock_code: str
    stock_name: str
    sector: str
    is_t0_able: bool
    min_buy_qty: int
    trade_unit: int
    short_name: str
    stktype: int
    scale: int
    created_at: datetime
    updated_at: datetime
