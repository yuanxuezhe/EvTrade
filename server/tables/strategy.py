"""
server/tables/strategy.py — 自动生成 (tables-codegen skill)

表: `strategy`  (10 字段, 主键: ['strategy_id'])
描述: MySQL table `strategy`

⚠️ 不要手动修改本文件 — 任何字段/主键变更请重新跑 tables-codegen
"""
from datetime import datetime
from server.tables.base import TableBase, Row
from typing import Any
from typing import Any, ClassVar, Optional, Tuple


class Strategy(TableBase):
    """MySQL table `strategy`

    自动生成，继承 TableBase 获得标准方法:
      - query_one(**pk)              按主键查单行 → Row | None
      - upsert_one(data, **pk)       INSERT OR UPDATE（统一写入入口）
      - delete_one(**pk)             按主键 DELETE → bool
      - query_all(order)             全表查询 → List[Row]
      - query_by(field, value)       单字段过滤
      - query_by_fields(filters)     多字段 AND 过滤

    主键: ['strategy_id']
    """

    __tablename__: ClassVar[str] = 'strategy'
    __pk_fields__: ClassVar[Tuple[str, ...]] = ('strategy_id',)
    __auto_increment_pk__: ClassVar[str | None] = 'strategy_id'

    __fields__: ClassVar[dict] = {
        'strategy_id': '',
        'user_id': '',
        'script_id': '',
        'name': '',
        'status': '',
        'is_public': '策略是否公开: 0=私有 1=公开',
        'stock_code': '策略绑定标的 (新建时必填)',
        'best_params': '',
        'created_at': '',
        'updated_at': ''
    }

    __field_types__: ClassVar[dict] = {
        'strategy_id': 'int',
        'user_id': 'int',
        'script_id': 'varchar(64)',
        'name': 'varchar(64)',
        'status': 'varchar(16)',
        'is_public': 'tinyint',
        'stock_code': 'varchar(16)',
        'best_params': 'json',
        'created_at': 'datetime',
        'updated_at': 'datetime'
    }

    # 字段 type hints (IDE 智能提示用, 运行时不影响行为)
    strategy_id: int
    user_id: int
    script_id: str
    name: str
    status: str
    is_public: int
    stock_code: Optional[str]
    best_params: Any
    created_at: datetime
    updated_at: datetime
