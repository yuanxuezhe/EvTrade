"""
server/tables/strategy_audit.py — 自动生成 (tables-codegen skill)

表: `strategy_audit`  (13 字段, 主键: ['id'])
描述: MySQL table `strategy_audit`

⚠️ 不要手动修改本文件 — 任何字段/主键变更请重新跑 tables-codegen
"""
from datetime import datetime
from server.tables.base import TableBase, Row
from typing import Any, ClassVar, Tuple


class StrategyAudit(TableBase):
    """MySQL table `strategy_audit`

    自动生成，继承 TableBase 获得标准方法:
      - query_one(**pk)              按主键查单行 → Row | None
      - upsert_one(data, **pk)       INSERT OR UPDATE（统一写入入口）
      - delete_one(**pk)             按主键 DELETE → bool
      - query_all(order)             全表查询 → List[Row]
      - query_by(field, value)       单字段过滤
      - query_by_fields(filters)     多字段 AND 过滤

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
