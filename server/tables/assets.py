"""
server/tables/assets.py — 自动生成 (v80.2 tables-codegen skill)

表: `assets`  (7 字段, 主键: ['id'])
描述: MySQL table `assets`

⚠️ 不要手动修改本文件 — 任何字段/主键变更请重新跑 scripts/gen_tables.py
   (skill: evtrade-table-codegen)
"""
from datetime import datetime
from server.tables.base import TableBase, Row
from typing import Any, ClassVar, Tuple


class Assets(TableBase):
    """MySQL table `assets`

    自动生成于 v80.2 架构调整, 继承 TableBase 获得 5 个标准方法:
      - query_one(**pk)            按主键查单行 → Row | None
      - add_one(data: dict)        INSERT 一行 → Row
      - update_one(data, **pk)     按主键 UPDATE → Row
      - delete_one(**pk)           按主键 DELETE → bool
      - query_all(order, page, page_size)  分页查询 → List[Row]

    主键: ['id']
    """

    __tablename__: ClassVar[str] = 'assets'
    __pk_fields__: ClassVar[Tuple[str, ...]] = ('id',)
    __auto_increment_pk__: ClassVar[str | None] = None
    __fields__: ClassVar[dict] = {
        'id': '',
        'cash': '',
        'available': '',         # v110: 可用资金
        'frozen_cash': '',
        'market_value': '',
        'total_asset': '',
        'last_asset': '',         # v114: 期初总资产 (早上 init 锁定)
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
        'last_asset': 'float',    # v114
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
    last_asset: float           # v114
    synced_at: datetime
    synced_from: str
