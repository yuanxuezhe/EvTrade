"""
server/tables/strategy_regime.py — 自动生成 (v80.2 tables-codegen skill)

表: `strategy_regime`  (11 字段, 主键: ['id'])
描述: MySQL table `strategy_regime`

⚠️ 不要手动修改本文件 — 任何字段/主键变更请重新跑 scripts/gen_tables.py
   (skill: evtrade-table-codegen)
"""
from datetime import datetime
from server.tables.base import TableBase, Row
from typing import Any, ClassVar, Tuple


class StrategyRegime(TableBase):
    """MySQL table `strategy_regime`

    自动生成于 v80.2 架构调整, 继承 TableBase 获得 5 个标准方法:
      - query_one(**pk)            按主键查单行 → Row | None
      - add_one(data: dict)        INSERT 一行 → Row
      - update_one(data, **pk)     按主键 UPDATE → Row
      - delete_one(**pk)           按主键 DELETE → bool
      - query_all(order, page, page_size)  分页查询 → List[Row]

    主键: ['id']
    """

    __tablename__: ClassVar[str] = 'strategy_regime'
    __pk_fields__: ClassVar[Tuple[str, ...]] = ('id',)
    __auto_increment_pk__: ClassVar[str | None] = 'id'

    __fields__: ClassVar[dict] = {
        'id': '',
        'strategy_id': '',
        'name': '',
        'priority': '',
        'required_flags': '',
        'exclude_flags': '',
        'base_volume': '',
        'clear_position': '',
        'enabled': '',
        'created_at': '',
        'updated_at': ''
    }

    __field_types__: ClassVar[dict] = {
        'id': 'int',
        'strategy_id': 'int',
        'name': 'varchar(64)',
        'priority': 'int',
        'required_flags': 'text',
        'exclude_flags': 'text',
        'base_volume': 'int',
        'clear_position': 'tinyint(1)',
        'enabled': 'tinyint(1)',
        'created_at': 'datetime',
        'updated_at': 'datetime'
    }

    # 字段 type hints (IDE 智能提示用, 运行时不影响行为)
    id: int
    strategy_id: int
    name: str
    priority: int
    required_flags: str
    exclude_flags: str
    base_volume: int
    clear_position: bool
    enabled: bool
    created_at: datetime
    updated_at: datetime
