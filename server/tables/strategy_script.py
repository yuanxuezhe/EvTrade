"""
server/tables/strategy_script.py — 手动维护 (迁移后由 migration + 人工调整)

表: `strategy_script`  (10 字段, 复合主键: ['user_id', 'id'])
描述: 脚本策略：用户编写的 Python 源码 + 参数 schema

PK 变更 (2026-08-04):
- 原 PK = id (AUTO_INCREMENT INT)  →  新 PK = (user_id, id) 复合
- id 列类型: int → varchar(64), 用户自命名 (通常 = name 或文件名)
- 同用户 id 唯一, 不同用户可重名
- 新增 is_public TINYINT: 是否公开 (0=私有 1=公开), 默认 0
- 列表查询: 用户看自己的 + 公开的 (user_id = me OR is_public = 1)
"""
from datetime import datetime
from server.tables.base import TableBase, Row
from typing import Any
from typing import Any, ClassVar, Tuple


class StrategyScript(TableBase):
    """脚本策略：用户编写的 Python 源码 + 参数 schema

    主键: ['user_id', 'id'] 复合主键 (2026-08-04)
    """

    __tablename__: ClassVar[str] = 'strategy_script'
    __pk_fields__: ClassVar[Tuple[str, ...]] = ('user_id', 'id')
    __auto_increment_pk__: ClassVar[str | None] = None  # 2026-08-04: 不再有自增 PK

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
        'is_public': 'tinyint',
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
    is_public: int  # 0/1
    created_at: datetime
    updated_at: datetime