"""
server/tables/assets.py — 自动生成 (tables-codegen skill)

表: `assets`  (9 字段, 主键: ['id'])
描述: MySQL table `assets`

⚠️ 不要手动修改本文件 — 任何字段/主键变更请重新跑 tables-codegen
"""
from datetime import datetime
from server.tables.base import TableBase, Row
from typing import Any, ClassVar, Tuple


class Assets(TableBase):
    """MySQL table `assets`

    自动生成，继承 TableBase 获得标准方法:
      - query_one(**pk)              按主键查单行 → Row | None
      - upsert_one(data, **pk)       INSERT OR UPDATE（统一写入入口）
      - delete_one(**pk)             按主键 DELETE → bool
      - query_all(order)             全表查询 → List[Row]
      - query_by(field, value)       单字段过滤
      - query_by_fields(filters)     多字段 AND 过滤

    主键: ['id']
    """

    __tablename__: ClassVar[str] = 'assets'
    __pk_fields__: ClassVar[Tuple[str, ...]] = ('id',)
    __auto_increment_pk__: ClassVar[str | None] = None

    __fields__: ClassVar[dict] = {
        'id': '',
        'cash': '',
        'available': '',
        'frozen_cash': '',
        'market_value': '',
        'total_asset': '',
        'last_asset': '',
        'synced_at': '',
        'synced_from': ''
    }

    __field_types__: ClassVar[dict] = {
        'id': 'int',
        'cash': 'float',
        'available': 'float',
        'frozen_cash': 'float',
        'market_value': 'float',
        'total_asset': 'float',
        'last_asset': 'float',
        'synced_at': 'datetime',
        'synced_from': 'varchar(16)'
    }

    # 字段 type hints (IDE 智能提示用, 运行时不影响行为)
    id: int
    cash: float
    available: float
    frozen_cash: float
    market_value: float
    total_asset: float
    last_asset: float
    synced_at: datetime
    synced_from: str
