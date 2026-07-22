"""
server/tables/strategy_audit.py — 自动生成 (v80.2 tables-codegen skill)

表: `strategy_audit`  (13 字段, 主键: ['id'])
描述: MySQL table `strategy_audit`

⚠️ 不要手动修改本文件 — 任何字段/主键变更请重新跑 scripts/gen_tables.py
   (skill: evtrade-table-codegen)
"""
from datetime import datetime
from server.tables.base import TableBase, Row
from typing import Any, ClassVar, Tuple


class StrategyAudit(TableBase):
    """MySQL table `strategy_audit`

    自动生成于 v80.2 架构调整, 继承 TableBase 获得 5 个标准方法:
      - query_one(**pk)            按主键查单行 → Row | None
      - add_one(data: dict)        INSERT 一行 → Row
      - update_one(data, **pk)     按主键 UPDATE → Row
      - delete_one(**pk)           按主键 DELETE → bool
      - query_all(order, page, page_size)  分页查询 → List[Row]

    主键: ['id']
    """

    __tablename__: ClassVar[str] = 'strategy_audit'
    __pk_fields__: ClassVar[Tuple[str, ...]] = ('id',)
    __auto_increment_pk__: ClassVar[str | None] = 'id'

    __fields__: ClassVar[dict] = {
        'id': '',
        'strategy_id': '',
        'regime_id': '',
        'trd_date': '',
        'trigger_type': '',
        'flags_active': '',
        'current_price': '',
        'position_vol': '',
        'base_volume': '',
        'action_payload': '',
        'order_no': '',
        'reject_reason': '',
        'created_at': ''
    }

    __field_types__: ClassVar[dict] = {
        'id': 'int',
        'strategy_id': 'int',
        'regime_id': 'int',
        'trd_date': 'varchar(8)',
        'trigger_type': 'varchar(32)',
        'flags_active': 'text',
        'current_price': 'float',
        'position_vol': 'int',
        'base_volume': 'int',
        'action_payload': 'text',
        'order_no': 'varchar(8)',
        'reject_reason': 'varchar(255)',
        'created_at': 'datetime'
    }

    # 字段 type hints (IDE 智能提示用, 运行时不影响行为)
    id: int
    strategy_id: int
    regime_id: int
    trd_date: str
    trigger_type: str
    flags_active: str
    current_price: float
    position_vol: int
    base_volume: int
    action_payload: str
    order_no: str
    reject_reason: str
    created_at: datetime
