"""
server/tables/rbac.py — RBAC 3 张表 (roles-module change 2026-09-21)

3 张表 (roles / user_roles / role_permissions) 的 TableBase 类.
合并到一个 rbac.py 文件 (3 表都极简单, 拆 3 文件意义不大).

⚠️ 手写 (跟 quote_sync_config 同模式, schema.yml 已同步).
"""
from datetime import datetime
from typing import ClassVar, Tuple

from server.tables.base import TableBase


class Roles(TableBase):
    """角色定义: 主键 id (自增), name 唯一"""

    __tablename__: ClassVar[str] = 'roles'
    __pk_fields__: ClassVar[Tuple[str, ...]] = ('id',)
    __auto_increment_pk__: ClassVar[str | None] = 'id'

    __fields__: ClassVar[dict] = {
        'id': '行主键',
        'name': '角色名 (英文唯一 key, 代码用)',
        'display_name': '显示名 (中文)',
        'description': '描述',
        'is_builtin': '1=内置不可删 (super_admin/admin/trader/viewer)',
        'created_at': '创建时间',
        'updated_at': '更新时间',
    }

    __field_types__: ClassVar[dict] = {
        'id': 'int',
        'name': 'varchar(64)',
        'display_name': 'varchar(128)',
        'description': 'varchar(255)',
        'is_builtin': 'tinyint(1)',
        'created_at': 'datetime',
        'updated_at': 'datetime',
    }

    id: int
    name: str
    display_name: str
    description: str | None
    is_builtin: bool
    created_at: datetime | None
    updated_at: datetime | None


class UserRoles(TableBase):
    """用户 ↔ 角色 多对多: 复合 PK (user_id, role_id)"""

    __tablename__: ClassVar[str] = 'user_roles'
    __pk_fields__: ClassVar[Tuple[str, ...]] = ('user_id', 'role_id')
    __auto_increment_pk__: ClassVar[str | None] = None

    __fields__: ClassVar[dict] = {
        'user_id': 'users.id',
        'role_id': 'roles.id',
        'granted_at': '授权时间',
        'granted_by': '授权人 users.id (NULL=系统)',
    }

    __field_types__: ClassVar[dict] = {
        'user_id': 'int',
        'role_id': 'int',
        'granted_at': 'datetime',
        'granted_by': 'int',
    }

    user_id: int
    role_id: int
    granted_at: datetime | None
    granted_by: int | None


class RolePermissions(TableBase):
    """角色 → 页面权限: 复合 PK (role_id, page_key). page_key 是前端路由 meta.page_key 字符串"""

    __tablename__: ClassVar[str] = 'role_permissions'
    __pk_fields__: ClassVar[Tuple[str, ...]] = ('role_id', 'page_key')
    __auto_increment_pk__: ClassVar[str | None] = None

    __fields__: ClassVar[dict] = {
        'role_id': 'roles.id',
        'page_key': '前端路由 meta.page_key (e.g. trade.t0, system-management.users)',
        'granted_at': '授权时间',
    }

    __field_types__: ClassVar[dict] = {
        'role_id': 'int',
        'page_key': 'varchar(64)',
        'granted_at': 'datetime',
    }

    role_id: int
    page_key: str
    granted_at: datetime | None