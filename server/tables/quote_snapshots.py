"""
server/tables/quote_snapshots.py — 自动生成 (tables-codegen skill)

表: `quote_snapshots`  (30 字段, 主键: ['id'])
描述: MySQL table `quote_snapshots`

⚠️ 不要手动修改本文件 — 任何字段/主键变更请重新跑 tables-codegen
"""
from datetime import datetime
from server.tables.base import TableBase, Row
from typing import Any, ClassVar, Tuple


class QuoteSnapshots(TableBase):
    """MySQL table `quote_snapshots`

    自动生成，继承 TableBase 获得标准方法:
      - query_one(**pk)              按主键查单行 → Row | None
      - upsert_one(data, **pk)       INSERT OR UPDATE（统一写入入口）
      - delete_one(**pk)             按主键 DELETE → bool
      - query_all(order)             全表查询 → List[Row]
      - query_by(field, value)       单字段过滤
      - query_by_fields(filters)     多字段 AND 过滤

    主键: ['id']
    """

    __tablename__: ClassVar[str] = 'quote_snapshots'
    __pk_fields__: ClassVar[Tuple[str, ...]] = ('id',)
    __auto_increment_pk__: ClassVar[str | None] = 'id'

    __fields__: ClassVar[dict] = {
        'id': '',
        'stock_code': '',
        'last_price': '',
        'open_price': '',
        'high_price': '',
        'low_price': '',
        'prev_close': '',
        'volume': '',
        'amount': '',
        'bid1_price': '',
        'bid1_vol': '',
        'bid2_price': '',
        'bid2_vol': '',
        'bid3_price': '',
        'bid3_vol': '',
        'bid4_price': '',
        'bid4_vol': '',
        'bid5_price': '',
        'bid5_vol': '',
        'ask1_price': '',
        'ask1_vol': '',
        'ask2_price': '',
        'ask2_vol': '',
        'ask3_price': '',
        'ask3_vol': '',
        'ask4_price': '',
        'ask4_vol': '',
        'ask5_price': '',
        'ask5_vol': '',
        'ts': ''
    }

    __field_types__: ClassVar[dict] = {
        'id': 'int',
        'stock_code': 'varchar(16)',
        'last_price': 'float',
        'open_price': 'float',
        'high_price': 'float',
        'low_price': 'float',
        'prev_close': 'float',
        'volume': 'int',
        'amount': 'float',
        'bid1_price': 'float',
        'bid1_vol': 'int',
        'bid2_price': 'float',
        'bid2_vol': 'int',
        'bid3_price': 'float',
        'bid3_vol': 'int',
        'bid4_price': 'float',
        'bid4_vol': 'int',
        'bid5_price': 'float',
        'bid5_vol': 'int',
        'ask1_price': 'float',
        'ask1_vol': 'int',
        'ask2_price': 'float',
        'ask2_vol': 'int',
        'ask3_price': 'float',
        'ask3_vol': 'int',
        'ask4_price': 'float',
        'ask4_vol': 'int',
        'ask5_price': 'float',
        'ask5_vol': 'int',
        'ts': 'datetime'
    }

    # 字段 type hints (IDE 智能提示用, 运行时不影响行为)
    id: int
    stock_code: str
    last_price: float
    open_price: float
    high_price: float
    low_price: float
    prev_close: float
    volume: int
    amount: float
    bid1_price: float
    bid1_vol: int
    bid2_price: float
    bid2_vol: int
    bid3_price: float
    bid3_vol: int
    bid4_price: float
    bid4_vol: int
    bid5_price: float
    bid5_vol: int
    ask1_price: float
    ask1_vol: int
    ask2_price: float
    ask2_vol: int
    ask3_price: float
    ask3_vol: int
    ask4_price: float
    ask4_vol: int
    ask5_price: float
    ask5_vol: int
    ts: datetime
