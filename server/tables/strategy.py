"""
server/tables/strategy.py — 自动生成 (tables-codegen skill)

表: `strategy`  (11 字段, 主键: ['id'])
描述: MySQL table `strategy`

⚠️ 不要手动修改本文件 — 任何字段/主键变更请重新跑 tables-codegen
"""
from datetime import datetime
from server.tables.base import TableBase, Row
from typing import Any
from typing import Any, ClassVar, Tuple


class Strategy(TableBase):
    """MySQL table `strategy`

    自动生成，继承 TableBase 获得标准方法:
      - query_one(**pk)              按主键查单行 → Row | None
      - upsert_one(data, **pk)       INSERT OR UPDATE（统一写入入口）
      - delete_one(**pk)             按主键 DELETE → bool
      - query_all(order)             全表查询 → List[Row]
      - query_by(field, value)       单字段过滤
      - query_by_fields(filters)     多字段 AND 过滤

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
        'updated_at': '',
        't0_params': 'T0策略参数JSON'
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
        'updated_at': 'datetime',
        't0_params': 'json'
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
    t0_params: Any
