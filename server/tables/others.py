"""
server/tables/others.py — 非主键查询集合 (v80.3)

仅当 Query/Add/Upd/Del/QueryAll 不够用时, 在这里写专用查询。
原则:
- 每个函数服务一个调用场景 (来自具体业务代码)
- 命名: Query<表>By<字段>  / Query<表>By<复合字段>
- 返回 List[Row] / Row / int, 跟 base.py 5 方法风格一致
- 内部用基类 get_conn() context manager
- **不引入 ORM** —— 纯 SQL

当前所有非主键查询 (按表汇总):

  Order (15 处):
    - QueryOrdersByTrdDateAndStockCode(trd_date, stock_code) — t0_stats
    - QueryOrdersByUserDefIn(allowed) — t0_stats
    - QueryOrdersByTrdDate(trd_date) — t0_aggregate
    - QueryOrdersByTrdDateGte(cutoff) — t0_aggregate
    - QueryOrdersByTrdDate(trd_date) — orders/query
    - UnsetTaskIdByTaskId(task_id) — t0/tasks (批量 UPDATE)
    - QueryOrdersByTaskId(task_id) — t0/tasks
    - QueryOrdersByOrderNo(order_no) — strategy/engine

  Position (6 处):
    - QueryPositionByStockCode(stock_code) — position_adjust
    - QueryPositionByStockCode(stock_code) — t0/tasks

  QuoteSnapshot (3 处):
    - QueryLatestQuoteSnapshotByStockCode(stock_code) — t0/tasks, push/trd
    - QueryQuoteSnapshotByStockCodeAndPrevCloseGt0(stock_code) — strategy/quote_consumer

  ReconcileReport (2 处):
    - QueryReconcileReportsSince(cutoff) — admin/reconcile
    - QueryReconcileReportByTrdDateModeCreatedAt(trd_date, mode, ts) — admin/reconcile

  Stock (5 处):
    - QueryStockByStockCode(stock_code) — repo/stocks (已用 GetStockInfo 覆盖)

  Strategy (4 处):
    - QueryActiveStrategies() — strategy/quote_consumer
    - QueryActiveStrategyByStockCode(stock_code) — strategy/quote_consumer
    - QueryStrategyById(strategy_id) — strategy/repository
    - QueryStrategiesByUserId(user_id) — strategy/repository

  StrategyGrid (1 处):
    - QueryStrategyGridById(grid_id) — strategy/repository

  StrategyRegime (1 处):
    - QueryStrategyRegimeById(regime_id) — strategy/repository

  SysConfig (3 处):
    - QuerySysConfigsByUserZero() — sysconfig
    - QuerySysConfigByUserAndKey(user, key) — sysconfig (已用 get_value 覆盖)

  SysStatus (1 处):
    - QuerySysStatusById(id) — reconcile (id 固定 1)

  T0Task (8 处):
    - QueryT0TaskById(id) — services/t0/tasks (已用 get_t0_task 覆盖)

  Trade (6 处):
    - QueryTradesByTrdDate(trd_date) — t0_aggregate
    - QueryTradesByTrdDateGte(cutoff) — t0_aggregate
    - QueryTradesByOrderNoIn(order_no_set) — t0/tasks
    - QueryTradeByTrdDateAndOrderNoAndTradeId(trd_date, order_no, trade_id) — push/trd

  User (8 处):
    - QueryUserByUsername(username) — auth, users
    - QueryUserById(user_id) — users
    - CountActiveAdminUsers() — users
    - CountAdminUsers() — users
"""
from typing import List, Optional
from sqlalchemy import text
from .base import get_conn, Row, exec_sql
from .orders import Orders
from .positions import Positions
from .quote_snapshots import QuoteSnapshots
from .reconcile_report import ReconcileReport
from .stocks import Stocks
from .strategy import Strategy
from .strategy_grid import StrategyGrid
from .strategy_regime import StrategyRegime
from .sys_config import SysConfig
from .sys_status import SysStatus
from .t0_tasks import T0Tasks
from .trades import Trades
from .users import Users


# ============================================================================
# Order 非主键查询
# ============================================================================

def QueryOrdersByTrdDateAndStockCode(trd_date: str, stock_code: str) -> List[Row]:
    """t0_stats: 按交易日 + 标的查所有 Order"""
    with get_conn() as conn:
        cur = exec_sql(conn,
            "SELECT * FROM orders WHERE trd_date=%s AND stock_code=%s ORDER BY order_no",
            (trd_date, stock_code)
        )
        return [Orders._row_from_mapping(row) for row in cur.mappings().fetchall()]


def QueryOrdersByUserDefIn(allowed: List[str]) -> List[Row]:
    """t0_stats: user_def IN (allowed) — 查用户标记的订单"""
    if not allowed:
        return []
    placeholders = ",".join(["%s"] * len(allowed))
    with get_conn() as conn:
        cur = exec_sql(conn,
            f"SELECT * FROM orders WHERE user_def IN ({placeholders}) ORDER BY trd_date DESC, order_no",
            tuple(allowed)
        )
        return [Orders._row_from_mapping(row) for row in cur.mappings().fetchall()]


def QueryOrdersByTrdDate(trd_date: str) -> List[Row]:
    """t0_aggregate / orders/query: 按交易日查所有 Order"""
    with get_conn() as conn:
        cur = exec_sql(conn,
            "SELECT * FROM orders WHERE trd_date=%s ORDER BY order_no",
            (trd_date,)
        )
        return [Orders._row_from_mapping(row) for row in cur.mappings().fetchall()]


def QueryOrdersByTrdDateGte(cutoff: str) -> List[Row]:
    """t0_aggregate: 查 cutoff 之后所有 Order"""
    with get_conn() as conn:
        cur = exec_sql(conn,
            "SELECT * FROM orders WHERE trd_date>=%s ORDER BY trd_date DESC, order_no",
            (cutoff,)
        )
        return [Orders._row_from_mapping(row) for row in cur.mappings().fetchall()]


def UnsetTaskIdByTaskId(task_id: int) -> int:
    """t0/tasks: 批量 UPDATE 把 order.task_id 置 NULL"""
    with get_conn() as conn:
        cur = exec_sql(conn,
            "UPDATE orders SET task_id=NULL WHERE task_id=%s",
            (task_id,)
        )
        conn.commit()
        return cur.rowcount


def QueryOrdersByTaskId(task_id: int) -> List[Row]:
    """t0/tasks: 查某个任务关联的所有 Order"""
    with get_conn() as conn:
        cur = exec_sql(conn,
            "SELECT * FROM orders WHERE task_id=%s ORDER BY order_no",
            (task_id,)
        )
        return [Orders._row_from_mapping(row) for row in cur.mappings().fetchall()]


def QueryOrderByOrderNo(order_no: str) -> Optional[Row]:
    """strategy/engine: 按 order_no 查单个 Order (注意非主键, 需 trd_date 一起)"""
    with get_conn() as conn:
        cur = exec_sql(conn,
            "SELECT * FROM orders WHERE order_no=%s LIMIT 1",
            (order_no,)
        )
        row = cur.mappings().fetchone()
        return Orders._row_from_mapping(row) if row else None


# ============================================================================
# Position 非主键查询
# ============================================================================

def QueryPositionByStockCode(stock_code: str) -> Optional[Row]:
    """position_adjust / t0/tasks: 按 stock_code 查持仓"""
    with get_conn() as conn:
        cur = exec_sql(conn,
            "SELECT * FROM positions WHERE stock_code=%s LIMIT 1",
            (stock_code,)
        )
        row = cur.mappings().fetchone()
        return Positions._row_from_mapping(row) if row else None


# ============================================================================
# QuoteSnapshot 非主键查询
# ============================================================================

def QueryLatestQuoteSnapshotByStockCode(stock_code: str) -> Optional[Row]:
    """t0/tasks, push/trd: 查某个标的最新一条行情快照"""
    with get_conn() as conn:
        cur = exec_sql(conn,
            "SELECT * FROM quote_snapshots WHERE stock_code=%s ORDER BY ts DESC LIMIT 1",
            (stock_code,)
        )
        row = cur.mappings().fetchone()
        return QuoteSnapshots._row_from_mapping(row) if row else None


def QueryQuoteSnapshotByStockCodeAndPrevCloseGt0(stock_code: str) -> Optional[Row]:
    """strategy/quote_consumer: 查 prev_close>0 的最新行情"""
    with get_conn() as conn:
        cur = exec_sql(conn,
            "SELECT * FROM quote_snapshots WHERE stock_code=%s AND prev_close>0 ORDER BY ts DESC LIMIT 1",
            (stock_code,)
        )
        row = cur.mappings().fetchone()
        return QuoteSnapshots._row_from_mapping(row) if row else None


# ============================================================================
# ReconcileReport 非主键查询
# ============================================================================

def QueryReconcileReportsSince(cutoff) -> List[Row]:
    """admin/reconcile: 查 cutoff 之后的对账报告 (按 created_at desc)"""
    with get_conn() as conn:
        cur = exec_sql(conn,
            "SELECT * FROM reconcile_report WHERE created_at>=%s ORDER BY created_at DESC",
            (cutoff,)
        )
        return [ReconcileReport._row_from_mapping(row) for row in cur.mappings().fetchall()]


def QueryReconcileReportByTrdDateModeCreatedAt(trd_date: str, mode: str, ts) -> Optional[Row]:
    """admin/reconcile: 按复合字段查单条"""
    with get_conn() as conn:
        cur = exec_sql(conn,
            "SELECT * FROM reconcile_report WHERE trd_date=%s AND mode=%s AND created_at=%s LIMIT 1",
            (trd_date, mode, ts)
        )
        row = cur.mappings().fetchone()
        return ReconcileReports._row_from_mapping(row) if row else None


# ============================================================================
# Strategy / StrategyGrid / StrategyRegime 非主键查询
# ============================================================================

def QueryActiveStrategies() -> List[Row]:
    """strategy/quote_consumer: 所有启用的策略"""
    with get_conn() as conn:
        cur = exec_sql(conn,
            "SELECT * FROM strategy WHERE status='active' ORDER BY id"
        )
        return [Strategy._row_from_mapping(row) for row in cur.mappings().fetchall()]


def QueryActiveStrategyByStockCode(stock_code: str) -> Optional[Row]:
    """strategy/quote_consumer: 按标的查启用策略"""
    with get_conn() as conn:
        cur = exec_sql(conn,
            "SELECT * FROM strategy WHERE stock_code=%s AND status='active' LIMIT 1",
            (stock_code,)
        )
        row = cur.mappings().fetchone()
        return Strategy._row_from_mapping(row) if row else None


def QueryStrategiesByUserId(user_id: int) -> List[Row]:
    """strategy/repository: 按 user_id 查策略"""
    with get_conn() as conn:
        cur = exec_sql(conn,
            "SELECT * FROM strategy WHERE user_id=%s ORDER BY id",
            (user_id,)
        )
        return [Strategy._row_from_mapping(row) for row in cur.mappings().fetchall()]


def QueryStrategyGridById(grid_id: int) -> Optional[Row]:
    """strategy/repository: 按 id 查网格 (非主键, 主键是 id 还是别的?)"""
    with get_conn() as conn:
        cur = exec_sql(conn,
            "SELECT * FROM strategy_grid WHERE id=%s LIMIT 1",
            (grid_id,)
        )
        row = cur.mappings().fetchone()
        return StrategyGrid._row_from_mapping(row) if row else None


def QueryStrategyRegimeById(regime_id: int) -> Optional[Row]:
    """strategy/repository: 按 id 查 regime"""
    with get_conn() as conn:
        cur = exec_sql(conn,
            "SELECT * FROM strategy_regime WHERE id=%s LIMIT 1",
            (regime_id,)
        )
        row = cur.mappings().fetchone()
        return StrategyRegime._row_from_mapping(row) if row else None


# ============================================================================
# SysConfig 非主键查询
# ============================================================================

def QuerySysConfigsByUserZero() -> List[Row]:
    """sysconfig: 查 user='0' (系统级配置) 的所有 SysConfig"""
    with get_conn() as conn:
        cur = exec_sql(conn,
            "SELECT * FROM sys_config WHERE user='0' ORDER BY cfg_key"
        )
        return [SysConfig._row_from_mapping(row) for row in cur.mappings().fetchall()]


def QuerySysStatusById(id: int) -> Optional[Row]:
    """reconcile: 按 id 查 SysStatus (主键就是 id)"""
    with get_conn() as conn:
        cur = exec_sql(conn,
            "SELECT * FROM sys_status WHERE id=%s LIMIT 1",
            (id,)
        )
        row = cur.mappings().fetchone()
        return SysStatus._row_from_mapping(row) if row else None


# ============================================================================
# Trade 非主键查询
# ============================================================================

def QueryTradesByTrdDate(trd_date: str) -> List[Row]:
    """t0_aggregate: 按交易日查所有 Trade"""
    with get_conn() as conn:
        cur = exec_sql(conn,
            "SELECT * FROM trades WHERE trd_date=%s ORDER BY order_no, trade_id",
            (trd_date,)
        )
        return [Trades._row_from_mapping(row) for row in cur.mappings().fetchall()]


def QueryTradesByTrdDateGte(cutoff: str) -> List[Row]:
    """t0_aggregate: 查 cutoff 之后所有 Trade"""
    with get_conn() as conn:
        cur = exec_sql(conn,
            "SELECT * FROM trades WHERE trd_date>=%s ORDER BY trd_date DESC, order_no, trade_id",
            (cutoff,)
        )
        return [Trades._row_from_mapping(row) for row in cur.mappings().fetchall()]


def QueryTradesByOrderNoIn(order_no_set: List[str]) -> List[Row]:
    """t0/tasks: 按 order_no IN (...) 查 Trade"""
    if not order_no_set:
        return []
    placeholders = ",".join(["%s"] * len(order_no_set))
    with get_conn() as conn:
        cur = exec_sql(conn,
            f"SELECT * FROM trades WHERE order_no IN ({placeholders}) ORDER BY trd_date, order_no",
            tuple(order_no_set)
        )
        return [Trades._row_from_mapping(row) for row in cur.mappings().fetchall()]


def QueryTradeByTrdDateAndOrderNoAndTradeId(trd_date: str, order_no: str, trade_id: str) -> Optional[Row]:
    """push/trd: 按复合字段查 Trade (非主键 — 主键是 (trd_date, order_no, trade_id) 但这正是主键, 应该用 QueryTradeByPk)"""
    return Trades.query_one(trd_date=trd_date, order_no=order_no, trade_id=trade_id)


# ============================================================================
# User 非主键查询
# ============================================================================

def QueryUserByUsername(username: str) -> Optional[Row]:
    """auth, users: 按 username 查 User"""
    with get_conn() as conn:
        cur = exec_sql(conn,
            "SELECT * FROM users WHERE username=%s LIMIT 1",
            (username,)
        )
        row = cur.mappings().fetchone()
        return Users._row_from_mapping(row) if row else None


def QueryUserById(user_id: int) -> Optional[Row]:
    """users: 按 id 查 User (主键查询, 用 Users.query_one 更合适)"""
    return Users.query_one(id=user_id)


def CountActiveAdminUsers() -> int:
    """users: 数 role='admin' AND is_active 的用户数"""
    with get_conn() as conn:
        cur = exec_sql(conn,
            "SELECT COUNT(*) FROM users WHERE role='admin' AND is_active"
        )
        return cur.scalar()


def CountAdminUsers() -> int:
    """users: 数所有 admin 用户"""
    with get_conn() as conn:
        cur = exec_sql(conn,
            "SELECT COUNT(*) FROM users WHERE role='admin'"
        )
        return cur.scalar()
