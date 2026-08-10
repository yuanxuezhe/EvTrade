"""
server/tables/order_no_seq.py — 自动生成 (tables-codegen skill)

表: `order_no_seq`  (3 字段, 主键: ['seq_name'])
描述: MySQL table `order_no_seq`

⚠️ 不要手动修改本文件 — 任何字段/主键变更请重新跑 tables-codegen
"""
from datetime import datetime
from server.tables.base import TableBase, Row
from typing import Any, ClassVar, Tuple


class OrderNoSeq(TableBase):
    """MySQL table `order_no_seq`

    自动生成，继承 TableBase 获得标准方法:
      - query_one(**pk)              按主键查单行 → Row | None
      - upsert_one(data, **pk)       INSERT OR UPDATE（统一写入入口）
      - delete_one(**pk)             按主键 DELETE → bool
      - query_all(order)             全表查询 → List[Row]
      - query_by(field, value)       单字段过滤
      - query_by_fields(filters)     多字段 AND 过滤

    主键: ['seq_name']
    """

    __tablename__: ClassVar[str] = 'order_no_seq'
    __pk_fields__: ClassVar[Tuple[str, ...]] = ('seq_name',)
    __auto_increment_pk__: ClassVar[str | None] = None

    __fields__: ClassVar[dict] = {
        'last_value': '',
        'updated_at': '',
        'seq_name': ''
    }

    __field_types__: ClassVar[dict] = {
        'last_value': 'int',
        'updated_at': 'datetime',
        'seq_name': 'varchar(32)'
    }

    # 字段 type hints (IDE 智能提示用, 运行时不影响行为)
    last_value: int
    updated_at: datetime
    seq_name: str
