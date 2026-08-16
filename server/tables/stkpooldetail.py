"""
server/tables/stkpooldetail.py — 证券池明细 (add-stkpool-module change)

表: `stkpooldetail`  (2 字段, 主键: ['id', 'stock_code'])
描述: 证券池明细 — share-id 模式: id 字段不自增, 与 stkpool.id 一一对应

⚠️ 关键差异 (share-id 模式):
  - 复合 PK (id, stock_code), id 字段 NOT auto_increment
  - 由应用层显式写入 id = stkpool.id
  - 同 (id, stock_code) 重复写入走 upsert (idempotent)
  - 删池自动 CASCADE 清明细 (FK ON DELETE CASCADE)

主键: ('id', 'stock_code')
自增: None   ← 关键: 共享主表 id, 不自增
"""
from typing import Any, ClassVar, Tuple

from server.tables.base import TableBase, Row


class StkpoolDetail(TableBase):
    """证券池明细: 复合 PK (id, stock_code), share-id 与 stkpool.id 关联"""

    __tablename__: ClassVar[str] = 'stkpooldetail'
    __pk_fields__: ClassVar[Tuple[str, ...]] = ('id', 'stock_code')
    __auto_increment_pk__: ClassVar[str | None] = None  # 关键: 不自增

    __fields__: ClassVar[dict] = {
        'id': '共享主表 id (不自增, 与 stkpool.id 一一对应)',
        'stock_code': '股票代码',
    }

    __field_types__: ClassVar[dict] = {
        'id': 'int',
        'stock_code': 'varchar(16)',
    }

    # 字段 type hints (IDE 智能提示)
    id: int
    stock_code: str
