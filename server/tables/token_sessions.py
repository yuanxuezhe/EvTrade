"""
server/tables/token_sessions.py — 自动生成 (tables-codegen skill)

表: `token_sessions`  (5 字段, 主键: ['token_hash'])
描述: REQ-AUTH-IDLE-001 token session cache (跨 worker 共享, 重启即清空)

⚠️ 不要手动修改本文件 — 任何字段/主键变更请重新跑 tables-codegen
"""
from datetime import datetime
from server.tables.base import TableBase, Row
from typing import ClassVar, Tuple


class TokenSessions(TableBase):
    """MySQL table `token_sessions`

    自动生成，继承 TableBase 获得标准方法:
      - query_one(**pk)              按主键查单行 → Row | None
      - upsert_one(data, **pk)       INSERT OR UPDATE（统一写入入口）
      - delete_one(**pk)             按主键 DELETE → bool
      - query_all(order)             全表查询 → List[Row]

    主键: ['token_hash']
    """

    __tablename__: ClassVar[str] = 'token_sessions'
    __pk_fields__: ClassVar[Tuple[str, ...]] = ('token_hash',)
    __auto_increment_pk__: ClassVar[str | None] = None

    __fields__: ClassVar[dict] = {
        'token_hash': '',
        'user_id': '',
        'role': '',
        'created_at': '',
        'last_seen_at': ''
    }

    __field_types__: ClassVar[dict] = {
        'token_hash': 'char(64)',
        'user_id': 'int',
        'role': 'varchar(16)',
        'created_at': 'datetime',
        'last_seen_at': 'datetime'
    }

    # 字段 type hints (IDE 智能提示用, 运行时不影响行为)
    token_hash: str
    user_id: int
    role: str
    created_at: datetime
    last_seen_at: datetime