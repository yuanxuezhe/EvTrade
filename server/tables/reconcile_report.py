"""
server/tables/reconcile_report.py — 自动生成 (v80.2 tables-codegen skill)

表: `reconcile_report`  (11 字段, 主键: ['trd_date', 'mode', 'created_at'])
描述: MySQL table `reconcile_report`

⚠️ 不要手动修改本文件 — 任何字段/主键变更请重新跑 scripts/gen_tables.py
   (skill: evtrade-table-codegen)
"""
from datetime import datetime
from server.tables.base import TableBase, Row
from typing import Any, ClassVar, Tuple


class ReconcileReport(TableBase):
    """MySQL table `reconcile_report`

    自动生成于 v80.2 架构调整, 继承 TableBase 获得 5 个标准方法:
      - query_one(**pk)            按主键查单行 → Row | None
      - add_one(data: dict)        INSERT 一行 → Row
      - update_one(data, **pk)     按主键 UPDATE → Row
      - delete_one(**pk)           按主键 DELETE → bool
      - query_all(order, page, page_size)  分页查询 → List[Row]

    主键: ['trd_date', 'mode', 'created_at']
    """

    __tablename__: ClassVar[str] = 'reconcile_report'
    __pk_fields__: ClassVar[Tuple[str, ...]] = ('trd_date', 'mode', 'created_at')
    __auto_increment_pk__: ClassVar[str | None] = None

    __fields__: ClassVar[dict] = {
        'trd_date': '',
        'mode': '',
        'created_at': '',
        'diffs_json': '',
        'broker_asset_json': '',
        'local_asset_json': '',
        'broker_positions_json': '',
        'local_positions_json': '',
        'rpc_status': '',
        'error_message': '',
        'created_by': ''
    }

    __field_types__: ClassVar[dict] = {
        'trd_date': 'varchar(8)',
        'mode': 'varchar(16)',
        'created_at': 'datetime',
        'diffs_json': 'text',
        'broker_asset_json': 'text',
        'local_asset_json': 'text',
        'broker_positions_json': 'text',
        'local_positions_json': 'text',
        'rpc_status': 'varchar(16)',
        'error_message': 'varchar(512)',
        'created_by': 'int'
    }

    # 字段 type hints (IDE 智能提示用, 运行时不影响行为)
    trd_date: str
    mode: str
    created_at: datetime
    diffs_json: str
    broker_asset_json: str
    local_asset_json: str
    broker_positions_json: str
    local_positions_json: str
    rpc_status: str
    error_message: str
    created_by: int
