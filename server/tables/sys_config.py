"""
server/tables/sys_config.py — 自动生成 (v80.2 tables-codegen skill)

表: `sys_config`  (6 字段, 主键: ['user', 'cfg_key'])
描述: MySQL table `sys_config`

⚠️ 不要手动修改本文件 — 任何字段/主键变更请重新跑 scripts/gen_tables.py
   (skill: evtrade-table-codegen)
"""
from datetime import datetime
from server.tables.base import TableBase, Row
from typing import Any, ClassVar, Tuple


class SysConfig(TableBase):
    """MySQL table `sys_config`

    自动生成于 v80.2 架构调整, 继承 TableBase 获得 5 个标准方法:
      - query_one(**pk)            按主键查单行 → Row | None
      - add_one(data: dict)        INSERT 一行 → Row
      - update_one(data, **pk)     按主键 UPDATE → Row
      - delete_one(**pk)           按主键 DELETE → bool
      - query_all(order, page, page_size)  分页查询 → List[Row]

    主键: ['user', 'cfg_key']
    """

    __tablename__: ClassVar[str] = 'sys_config'
    __pk_fields__: ClassVar[Tuple[str, ...]] = ('user', 'cfg_key')
    __auto_increment_pk__: ClassVar[str | None] = None

    __fields__: ClassVar[dict] = {
        'user': '',
        'cfg_key': '',
        'cfg_val': '',
        'desc': '',
        'updated_at': '',
        'updated_by': ''
    }

    __field_types__: ClassVar[dict] = {
        'user': 'varchar(64)',
        'cfg_key': 'varchar(64)',
        'cfg_val': 'varchar(512)',
        'desc': 'varchar(255)',
        'updated_at': 'datetime',
        'updated_by': 'varchar(64)'
    }

    # 字段 type hints (IDE 智能提示用, 运行时不影响行为)
    user: str
    cfg_key: str
    cfg_val: str
    desc: str
    updated_at: datetime
    updated_by: str
