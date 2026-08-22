"""
server/tables/strategy_order.py — 自动生成 (tables-codegen skill)

表: `strategy_order`  (13 字段, 主键: ['id'])
描述: 策略下单母单: 可重复启停, 子单按 parent_task_id 归因

⚠️ 不要手动修改本文件 — 任何字段/主键变更请重新跑 tables-codegen
"""
from datetime import datetime
from server.tables.base import TableBase, Row
from typing import Any, ClassVar, Tuple


class StrategyOrder(TableBase):
    """策略下单母单: 可重复启停, 子单按 parent_task_id 归因

    自动生成，继承 TableBase 获得标准方法:
      - query_one(**pk)              按主键查单行 → Row | None
      - upsert_one(data, **pk)       INSERT OR UPDATE（统一写入入口）
      - delete_one(**pk)             按主键 DELETE → bool
      - query_all(order)             全表查询 → List[Row]
      - query_by(field, value)       单字段过滤
      - query_by_fields(filters)     多字段 AND 过滤

    主键: ['id']
    """

    __tablename__: ClassVar[str] = 'strategy_order'
    __pk_fields__: ClassVar[Tuple[str, ...]] = ('id',)
    __auto_increment_pk__: ClassVar[str | None] = 'id'

    __fields__: ClassVar[dict] = {
        'id': '行主键',
        'task_id': '母单对外编号 (order_no_seq.strategy_order 生成器); 子单 orders.task_id 指向它',
        'user_id': 'owner',
        'strategy_id': '关联 strategy.strategy_id',
        'stock_code': '冗余自 strategy.stock_code (展示/过滤)',
        'status': 'stopped / running / closed',
        'active_task_id': '当前 live strategy_task.id (停止时转发 /internal/stop-task 用)',
        'run_count': '累计启动次数',
        'last_started_at': '',
        'last_stopped_at': '',
        'closed_at': '',
        'created_at': '',
        'updated_at': ''
    }

    __field_types__: ClassVar[dict] = {
        'id': 'int',
        'task_id': 'int',
        'user_id': 'int',
        'strategy_id': 'int',
        'stock_code': 'varchar(16)',
        'status': 'varchar(16)',
        'active_task_id': 'int',
        'run_count': 'int',
        'last_started_at': 'datetime',
        'last_stopped_at': 'datetime',
        'closed_at': 'datetime',
        'created_at': 'datetime',
        'updated_at': 'datetime'
    }

    # 字段 type hints (IDE 智能提示用, 运行时不影响行为)
    id: int
    task_id: int
    user_id: int
    strategy_id: int
    stock_code: str
    status: str
    active_task_id: int
    run_count: int
    last_started_at: datetime
    last_stopped_at: datetime
    closed_at: datetime
    created_at: datetime
    updated_at: datetime
