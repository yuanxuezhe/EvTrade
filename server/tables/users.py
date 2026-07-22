"""
server/tables/users.py — 自动生成 (v80.2 tables-codegen skill)

表: `users`  (11 字段, 主键: ['id'])
描述: MySQL table `users`

⚠️ 不要手动修改本文件 — 任何字段/主键变更请重新跑 scripts/gen_tables.py
   (skill: evtrade-table-codegen)
"""
from datetime import datetime
from server.tables.base import TableBase, Row
from typing import Any, ClassVar, Tuple


class Users(TableBase):
    """MySQL table `users`

    自动生成于 v80.2 架构调整, 继承 TableBase 获得 5 个标准方法:
      - query_one(**pk)            按主键查单行 → Row | None
      - add_one(data: dict)        INSERT 一行 → Row
      - update_one(data, **pk)     按主键 UPDATE → Row
      - delete_one(**pk)           按主键 DELETE → bool
      - query_all(order, page, page_size)  分页查询 → List[Row]

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
