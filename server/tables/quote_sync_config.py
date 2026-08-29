"""
server/tables/quote_sync_config.py — 行情同步任务表/配置 (his-quote-backfill)

表: `quote_sync_config`  (8 字段, 主键: ['stock_code'])
描述: 要跟踪并自动补全历史分钟行情的证券配置; last_loaded_date 是续传游标;
      status/error_msg 记录最近一次同步结果 (操作记录语义)

⚠️ 手写 (tables-codegen 子进程 gbk 解码 bug 绕过, 待 followup 修)

主键: ('stock_code',)
自增: None
"""
from datetime import datetime
from typing import ClassVar, Tuple

from server.tables.base import TableBase, Row


class QuoteSyncConfig(TableBase):
    """行情同步任务表: 主键 stock_code, 记录区间/游标/自动同步标志/最近结果"""

    __tablename__: ClassVar[str] = 'quote_sync_config'
    __pk_fields__: ClassVar[Tuple[str, ...]] = ('stock_code',)
    __auto_increment_pk__: ClassVar[str | None] = None

    __fields__: ClassVar[dict] = {
        'stock_code': '证券代码 (主键, 如 159992.SZ)',
        'start_date': '时间区间起点 YYYYMMDD',
        'end_date': '时间区间终点 YYYYMMDD (空串=开放, 补到昨天)',
        'last_loaded_date': '当前已加载到的日期 (续传游标)',
        'auto_sync': '启用自动同步标志 (1/0, 默认 1)',
        'status': '最近状态 (idle/running/success/failed, 默认 idle)',
        'error_msg': '最近失败原因 (默认空)',
        'updated_at': '最近同步时间',
    }

    __field_types__: ClassVar[dict] = {
        'stock_code': 'varchar(16)',
        'start_date': 'varchar(8)',
        'end_date': 'varchar(8)',
        'last_loaded_date': 'varchar(8)',
        'auto_sync': 'int',
        'status': 'varchar(16)',
        'error_msg': 'varchar(255)',
        'updated_at': 'datetime',
    }

    # 字段 type hints (IDE 智能提示)
    stock_code: str
    start_date: str
    end_date: str
    last_loaded_date: str
    auto_sync: int
    status: str
    error_msg: str
    updated_at: datetime | None
