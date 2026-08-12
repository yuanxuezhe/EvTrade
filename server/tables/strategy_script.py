"""
server/tables/strategy_script.py — 自动生成 (tables-codegen skill)

表: `strategy_script`  (10 字段, 主键: ['id', 'user_id'])
描述: 脚本策略：用户编写的 Python 源码 + 参数 schema

⚠️ 不要手动修改本文件 — 任何字段/主键变更请重新跑 tables-codegen
"""
from datetime import datetime
from server.tables.base import TableBase, Row
from typing import Any
from typing import Any, ClassVar, Tuple


class StrategyScript(TableBase):
    """脚本策略：用户编写的 Python 源码 + 参数 schema

    自动生成，继承 TableBase 获得标准方法:
      - query_one(**pk)              按主键查单行 → Row | None
      - upsert_one(data, **pk)       INSERT OR UPDATE（统一写入入口）
      - delete_one(**pk)             按主键 DELETE → bool
      - query_all(order)             全表查询 → List[Row]
      - query_by(field, value)       单字段过滤
      - query_by_fields(filters)     多字段 AND 过滤

    主键: ['id', 'user_id']
    """

    __tablename__: ClassVar[str] = 'strategy_script'
    __pk_fields__: ClassVar[Tuple[str, ...]] = ('id', 'user_id')
    __auto_increment_pk__: ClassVar[str | None] = None

    __fields__: ClassVar[dict] = {
        'id': '',
        'user_id': '',
        'name': '',
        'code': '',
        'params_schema': '',
        'description': '',
        'status': '',
        'is_public': '',
        'created_at': '',
        'updated_at': ''
    }

    __field_types__: ClassVar[dict] = {
        'id': 'varchar(64)',
        'user_id': 'int',
        'name': 'varchar(64)',
        'code': 'longtext',
        'params_schema': 'json',
        'description': 'varchar(255)',
        'status': 'varchar(16)',
        'is_public': 'tinyint(1)',
        'created_at': 'datetime',
        'updated_at': 'datetime'
    }

    # 字段 type hints (IDE 智能提示用, 运行时不影响行为)
    id: str
    user_id: int
    name: str
    code: str
    params_schema: Any
    description: str
    status: str
    is_public: bool
    created_at: datetime
    updated_at: datetime
