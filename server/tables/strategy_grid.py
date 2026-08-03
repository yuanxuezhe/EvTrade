"""
server/tables/strategy_grid.py — 自动生成 (tables-codegen skill)

表: `strategy_grid`  (12 字段, 主键: ['id'])
描述: MySQL table `strategy_grid`

⚠️ 不要手动修改本文件 — 任何字段/主键变更请重新跑 tables-codegen
"""
from datetime import datetime
from server.tables.base import TableBase, Row
from typing import Any, ClassVar, Tuple


class StrategyGrid(TableBase):
    """MySQL table `strategy_grid`

    自动生成，继承 TableBase 获得标准方法:
      - query_one(**pk)              按主键查单行 → Row | None
      - upsert_one(data, **pk)       INSERT OR UPDATE（统一写入入口）
      - delete_one(**pk)             按主键 DELETE → bool
      - query_all(order)             全表查询 → List[Row]
      - query_by(field, value)       单字段过滤
      - query_by_fields(filters)     多字段 AND 过滤

    主键: ['id']
    """

    __tablename__: ClassVar[str] = 'strategy_grid'
    __pk_fields__: ClassVar[Tuple[str, ...]] = ('id',)
    __auto_increment_pk__: ClassVar[str | None] = 'id'

    __fields__: ClassVar[dict] = {
        'id': '',
        'regime_id': '',
        'direction': '',
        'step_offset': '',
        'trigger_price': '',
        'volume': '',
        'max_fires': '',
        'fired_count': '',
        'enabled': '',
        'priority': '',
        'created_at': '',
        'updated_at': ''
    }

    __field_types__: ClassVar[dict] = {
        'id': 'int',
        'regime_id': 'int',
        'direction': 'varchar(8)',
        'step_offset': 'float',
        'trigger_price': 'float',
        'volume': 'int',
        'max_fires': 'int',
        'fired_count': 'int',
        'enabled': 'tinyint(1)',
        'priority': 'int',
        'created_at': 'datetime',
        'updated_at': 'datetime'
    }

    # 字段 type hints (IDE 智能提示用, 运行时不影响行为)
    id: int
    regime_id: int
    direction: str
    step_offset: float
    trigger_price: float
    volume: int
    max_fires: int
    fired_count: int
    enabled: bool
    priority: int
    created_at: datetime
    updated_at: datetime
