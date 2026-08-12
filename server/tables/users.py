"""
server/tables/users.py — 自动生成 (tables-codegen skill)

表: `users`  (11 字段, 主键: ['id'])
描述: MySQL table `users`

⚠️ 不要手动修改本文件 — 任何字段/主键变更请重新跑 tables-codegen
"""
from datetime import datetime
from server.tables.base import TableBase, Row
from typing import Any, ClassVar, Tuple


class Users(TableBase):
    """MySQL table `users`

    自动生成，继承 TableBase 获得标准方法:
      - query_one(**pk)              按主键查单行 → Row | None
      - upsert_one(data, **pk)       INSERT OR UPDATE（统一写入入口）
      - delete_one(**pk)             按主键 DELETE → bool
      - query_all(order)             全表查询 → List[Row]
      - query_by(field, value)       单字段过滤
      - query_by_fields(filters)     多字段 AND 过滤

    主键: ['id']
    """

    __tablename__: ClassVar[str] = 'users'
    __pk_fields__: ClassVar[Tuple[str, ...]] = ('id',)
    __auto_increment_pk__: ClassVar[str | None] = 'id'

    __fields__: ClassVar[dict] = {
        'id': '',
        'username': '',
        'password_hash': '',
        'email': '',
        'full_name': '',
        'role': '',
        'is_active': '',
        'must_change_password': '',
        'created_at': '',
        'updated_at': '',
        'last_login_at': ''
    }

    __field_types__: ClassVar[dict] = {
        'id': 'int',
        'username': 'varchar(64)',
        'password_hash': 'varchar(255)',
        'email': 'varchar(128)',
        'full_name': 'varchar(64)',
        'role': 'varchar(16)',
        'is_active': 'tinyint(1)',
        'must_change_password': 'tinyint(1)',
        'created_at': 'datetime',
        'updated_at': 'datetime',
        'last_login_at': 'datetime'
    }

    # 字段 type hints (IDE 智能提示用, 运行时不影响行为)
    id: int
    username: str
    password_hash: str
    email: str
    full_name: str
    role: str
    is_active: bool
    must_change_password: bool
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime
