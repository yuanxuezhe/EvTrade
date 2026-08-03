"""
server/tables/strategy_script_audit.py — 自动生成 (tables-codegen skill)

表: `strategy_script_audit`  (15 字段, 主键: ['id'])
描述: MySQL table `strategy_script_audit`

⚠️ 不要手动修改本文件 — 任何字段/主键变更请重新跑 tables-codegen
"""
from datetime import datetime
from server.tables.base import TableBase, Row
from typing import Any
from typing import Any, ClassVar, Tuple


class StrategyScriptAudit(TableBase):
    """MySQL table `strategy_script_audit`

    自动生成，继承 TableBase 获得标准方法:
      - query_one(**pk)              按主键查单行 → Row | None
      - upsert_one(data, **pk)       INSERT OR UPDATE（统一写入入口）
      - delete_one(**pk)             按主键 DELETE → bool
      - query_all(order)             全表查询 → List[Row]
      - query_by(field, value)       单字段过滤
      - query_by_fields(filters)     多字段 AND 过滤

    主键: ['id']
    """

    __tablename__: ClassVar[str] = 'strategy_script_audit'
    __pk_fields__: ClassVar[Tuple[str, ...]] = ('id',)
    __auto_increment_pk__: ClassVar[str | None] = 'id'

    __fields__: ClassVar[dict] = {
        'id': '',
        'task_id': '',
        'stime': 'bar/tick 时间 YYYYMMDDHHMMSS',
        'trd_date': '交易日 YYYYMMDD',
        'phase': 'bar / tick / on_init / on_finish',
        'trigger_type': 'BUY / SELL / SIGNAL / STOP / TP / INFO',
        'stock_code': '',
        'price': '',
        'volume': '',
        'indicators': '触发时指标快照 {MA5:..., RSI:...}',
        'state': '触发时状态 {position:N, cash:M}',
        'msg': '触发原因 / 用户描述',
        'order_no': '实盘 broker 订单号',
        'payload': '其他信息',
        'created_at': ''
    }

    __field_types__: ClassVar[dict] = {
        'id': 'bigint',
        'task_id': 'int',
        'stime': 'varchar(20)',
        'trd_date': 'varchar(8)',
        'phase': 'varchar(16)',
        'trigger_type': 'varchar(16)',
        'stock_code': 'varchar(16)',
        'price': 'float',
        'volume': 'int',
        'indicators': 'json',
        'state': 'json',
        'msg': 'text',
        'order_no': 'varchar(32)',
        'payload': 'json',
        'created_at': 'datetime'
    }

    # 字段 type hints (IDE 智能提示用, 运行时不影响行为)
    id: int
    task_id: int
    stime: str
    trd_date: str
    phase: str
    trigger_type: str
    stock_code: str
    price: float
    volume: int
    indicators: Any
    state: Any
    msg: str
    order_no: str
    payload: Any
    created_at: datetime
