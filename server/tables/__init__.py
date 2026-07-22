"""
server/tables/__init__.py — 统一导出所有表类 (v80.2 自动生成)

⚠️ 不要手动修改本文件 — 重新跑 scripts/gen_tables.py 自动更新
"""

from server.tables.base import (
    TableBase,
    Row,
    get_conn,
    transaction,        # v80.9: 事务 context manager
    aggregate,          # v80.9: SUM/COUNT/AVG/MAX/MIN 聚合
    scalar_query,       # v80.9: 单值查询
)  # noqa: F401

from server.tables.assets import Assets  # noqa: F401
from server.tables.order_no_seq import OrderNoSeq  # noqa: F401
from server.tables.orders import Orders  # noqa: F401
from server.tables.positions import Positions  # noqa: F401
from server.tables.quote_snapshots import QuoteSnapshots  # noqa: F401
from server.tables.reconcile_report import ReconcileReport  # noqa: F401
from server.tables.stocks import Stocks  # noqa: F401
from server.tables.strategy import Strategy  # noqa: F401
from server.tables.strategy_audit import StrategyAudit  # noqa: F401
from server.tables.strategy_grid import StrategyGrid  # noqa: F401
from server.tables.strategy_regime import StrategyRegime  # noqa: F401
from server.tables.sys_config import SysConfig  # noqa: F401
from server.tables.sys_status import SysStatus  # noqa: F401
from server.tables.t0_tasks import T0Tasks  # noqa: F401
from server.tables.trades import Trades  # noqa: F401
from server.tables.users import Users  # noqa: F401
