"""
server/tables/minute_bars.py — 历史分钟 K 线 (his-quote-backfill)

表: `minute_bars`  (8 字段, 主键: ['stock_code', 'stime'])
描述: broker his_hq 1m K 线落地, 多标的复用, 写入 ON DUPLICATE KEY UPDATE 幂等

⚠️ 手写 (tables-codegen 子进程 gbk 解码 bug 绕过, 待 followup 修):
  - 复合 PK (stock_code, stime), 均不自增
  - stime = 14 位 YYYYMMDDHHMMSS (broker/strategy_exec 全链路一致)
  - avg_price = VWAP = amount/(volume*100) 元/股 (A股 volume 单位是手)

主键: ('stock_code', 'stime')
自增: None
"""
from typing import ClassVar, Tuple

from server.tables.base import TableBase, Row


class MinuteBars(TableBase):
    """历史分钟 K 线: 复合 PK (stock_code, stime), 写入幂等"""

    __tablename__: ClassVar[str] = 'minute_bars'
    __pk_fields__: ClassVar[Tuple[str, ...]] = ('stock_code', 'stime')
    __auto_increment_pk__: ClassVar[str | None] = None  # 均不自增

    __fields__: ClassVar[dict] = {
        'stock_code': '证券代码 (如 159992.SZ)',
        'stime': '14 位 YYYYMMDDHHMMSS 时间戳',
        'open': '开盘 (元/股)',
        'close': '收盘 (元/股)',
        'high': '最高 (元/股)',
        'low': '最低 (元/股)',
        'avg_price': '均价 VWAP = amount/(volume*100) 元/股',
        'volume': '成交量 (手)',
    }

    __field_types__: ClassVar[dict] = {
        'stock_code': 'varchar(16)',
        'stime': 'varchar(16)',
        'open': 'float',
        'close': 'float',
        'high': 'float',
        'low': 'float',
        'avg_price': 'float',
        'volume': 'int',
    }

    # 字段 type hints (IDE 智能提示)
    stock_code: str
    stime: str
    open: float
    close: float
    high: float
    low: float
    avg_price: float
    volume: int
