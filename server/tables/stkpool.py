"""
server/tables/stkpool.py — 证券池主表 (add-stkpool-module change)

表: `stkpool`  (4 字段, 主键: ['id'])
描述: 证券池主表 — id 自增, name 唯一, remark 备注, created_at 创建时间

自动生成的等效模式 (本 change 手写, 模板对齐 strategy_order.py):
  - 集成 TableBase 获得标准方法:
    - query_one(**pk)              按主键查单行 → Row | None
    - upsert_one(data, **pk)       INSERT OR UPDATE（统一写入入口）
    - delete_one(**pk)             按主键 DELETE → bool
    - query_all(order)             全表查询 → List[Row]
    - query_by(field, value)       单字段过滤
    - query_by_fields(filters)     多字段 AND 过滤
    - query_by_in(field, values)   单字段 IN 过滤

主键: ('id',)
自增: id
"""
from datetime import datetime
from typing import Any, ClassVar, Tuple

from server.tables.base import TableBase, Row


class Stkpool(TableBase):
    """证券池主表: id 自增, name 唯一, remark 备注, created_at 创建时间"""

    __tablename__: ClassVar[str] = 'stkpool'
    __pk_fields__: ClassVar[Tuple[str, ...]] = ('id',)
    __auto_increment_pk__: ClassVar[str | None] = 'id'

    __fields__: ClassVar[dict] = {
        'id': '行主键 (自增)',
        'name': '池名 (唯一)',
        'remark': '备注',
        'created_at': '创建时间',
    }

    __field_types__: ClassVar[dict] = {
        'id': 'int',
        'name': 'varchar(64)',
        'remark': 'varchar(255)',
        'created_at': 'datetime',
    }

    # 字段 type hints (IDE 智能提示)
    id: int
    name: str
    remark: str
    created_at: datetime
