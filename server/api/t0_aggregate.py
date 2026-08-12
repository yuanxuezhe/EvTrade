"""
t0_aggregate.py — T0 敞口聚合 + 累计收益端点

GET /api/orders/t0-exposure?user_def=T0&trd_date=YYYYMMDD
  → 当日 / 多标的 / 按 user_def 聚合的买/卖/敞口/一键配平

GET /api/orders/t0-aggregate?user_def=T0&days=30
  → 跨期累计 + 按日/按股双视角 + 胜率/回报率

v81.4 改动（tables-migration）：
- 删 Depends(get_db) × 2 + sqlalchemy.orm.Session import + server.db.get_db
- db.query(Order).filter(…) → Orders.query_by(…) + 内存过滤
  (区间/复合查询 API 层不支持, 走内存过滤 — 数据量小, 走主键升序全表查)
- db.query(Position) → Positions.query_all() (positions 表行数 ≤ 持仓数, 量小)
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from server.db import db_session
from server.services.t0 import get_fee_config
from server.services.t0.aggregators import (
    aggregate_by_day,
    aggregate_by_stock,
    aggregate_summary,
    apply_user_def_filter,
)
from server.auth.deps import get_current_user
from server.models.user import User
from server.tables import Orders, Trades, Positions

router = APIRouter()


# ──────── Response Schemas ────────

class ExposurePositionOut(BaseModel):
    stock_code: str
    buy_volume: int
    sell_volume: int
    net_volume: int
    buy_amount: float
    sell_amount: float
    net_amount: float
    realized_pnl: float
    commission: float
    stamp_tax: float
    buy_commission: float
    day_fee: float
    order_count: int
    trade_count: int
    open_order_count: int
    position_volume: int
    cost_basis: float


class ExposureTotalsOut(BaseModel):
    buy_volume: int
    sell_volume: int
    net_volume: int
    buy_amount: float
    sell_amount: float
    net_amount: float
    realized_pnl: float
    commission_total: float
    stamp_tax_total: float
    buy_commission_total: float
    day_fee_total: float


class T0ExposureOut(BaseModel):
    trd_date: str
    user_def: str
    positions: List[ExposurePositionOut]
    totals: ExposureTotalsOut


class AggregateSummaryOut(BaseModel):
    total_realized: float
    total_commission: float
    total_stamp_tax: float
    total_buy_amount: float
    total_sell_amount: float
    win_days: int
    total_days: int
    win_rate: float
    return_rate: float
    trade_count: int
    order_count: int
    stocks_traded: int


class AggregateByDayOut(BaseModel):
    trd_date: str
    realized_pnl: float
    buy_amount: float
    sell_amount: float
    trade_count: int
    stock_count: int
    commission: float
    stamp_tax: float
    cum_pnl: float


class AggregateByStockOut(BaseModel):
    stock_code: str
    trade_count: int
    realized_pnl: float
    buy_amount: float
    sell_amount: float


class T0AggregateOut(BaseModel):
    user_def: str
    days: int
    summary: AggregateSummaryOut
    by_day: List[AggregateByDayOut]
    by_stock: List[AggregateByStockOut]


# ──────── Endpoints ────────

@router.get("/t0-exposure", response_model=T0ExposureOut)
async def get_t0_exposure(
    user_def: str = Query(default="T0", description="T0 标签键，空字符串=全部"),
    trd_date: Optional[str] = Query(
        default=None,
        description="交易日 YYYYMMDD，留空=当前激活日",
    ),
    _user: User = Depends(get_current_user),
):
    """当日多标的敞口聚合

    v81.4 tables-migration:
      原 db.query(Order).filter(Order.trd_date == trd_date).all()
      改 Orders.query_by('trd_date', trd_date)
    """
    from server.services.guards import resolve_active_trd_date

    if not trd_date:
        # v81.4 tables-migration: db_session() context manager 替代 Depends(get_db)
        with db_session() as db:
            trd_date = resolve_active_trd_date(db) or _today_str()

    fee_cfg = get_fee_config()
    # v81.4: 走 Orders/Trades/Positions tables API (主键升序, 数据量小)
    orders = Orders.query_by("trd_date", trd_date)
    trades = Trades.query_by("trd_date", trd_date)
    positions = _query_positions_dict()

    f_orders, f_trades = apply_user_def_filter(orders, trades, user_def)
    rows = aggregate_by_stock(f_trades, f_orders, positions, fee_cfg)

    # totals
    buy_vol = sum(r["buy_volume"] for r in rows)
    sell_vol = sum(r["sell_volume"] for r in rows)
    realized_total = sum(r["realized_pnl"] for r in rows)
    commission_total = sum(r["commission"] for r in rows)
    stamp_tax_total = sum(r["stamp_tax"] for r in rows)
    buy_commission_total = sum(r["buy_commission"] for r in rows)
    day_fee_total = sum(r["day_fee"] for r in rows)
    buy_amt = sum(r["buy_amount"] for r in rows)
    sell_amt = sum(r["sell_amount"] for r in rows)

    return T0ExposureOut(
        trd_date=trd_date,
        user_def=user_def,
        positions=[ExposurePositionOut(**r) for r in rows],
        totals=ExposureTotalsOut(
            buy_volume=buy_vol,
            sell_volume=sell_vol,
            net_volume=buy_vol - sell_vol,
            buy_amount=round(buy_amt, 2),
            sell_amount=round(sell_amt, 2),
            net_amount=round(buy_amt - sell_amt, 2),
            realized_pnl=round(realized_total, 2),
            commission_total=round(commission_total, 2),
            stamp_tax_total=round(stamp_tax_total, 2),
            buy_commission_total=round(buy_commission_total, 2),
            day_fee_total=round(day_fee_total, 2),
        ),
    )


@router.get("/t0-aggregate", response_model=T0AggregateOut)
async def get_t0_aggregate(
    user_def: str = Query(default="T0", description="T0 标签键，空字符串=全部"),
    days: int = Query(default=30, ge=1, le=365, description="回溯天数"),
    _user: User = Depends(get_current_user),
):
    """跨期累计 + 按日/按股聚合

    v81.4 tables-migration:
      原 db.query(Order).filter(Order.trd_date >= cutoff).all()
      改 Orders.query_all() + 内存过滤 (区间 API 层不支持, 数据量小)
    """
    from datetime import datetime, timedelta

    fee_cfg = get_fee_config()
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")

    # v81.4: 全表 + 内存过滤 (Orders/Trades 按 (trd_date, order_no) 复合 PK 升序全表查)
    all_orders = Orders.query_all()
    all_trades = Trades.query_all()
    orders = [o for o in all_orders if (o.trd_date or "") >= cutoff]
    trades = [t for t in all_trades if (t.trd_date or "") >= cutoff]
    positions = _query_positions_dict()

    f_orders, f_trades = apply_user_def_filter(orders, trades, user_def)

    by_stock_rows = aggregate_by_stock(f_trades, f_orders, positions, fee_cfg)
    by_day_rows = aggregate_by_day(f_trades, positions, fee_cfg)
    summary = aggregate_summary(by_day_rows, by_stock_rows, f_orders)

    # by_day 加 cum_pnl（累计盈亏）
    cum = 0.0
    by_day_with_cum = []
    for d in by_day_rows:
        cum += d["realized_pnl"]
        d2 = dict(d)
        d2["cum_pnl"] = round(cum, 2)
        by_day_with_cum.append(d2)

    return T0AggregateOut(
        user_def=user_def,
        days=days,
        summary=AggregateSummaryOut(**summary),
        by_day=[AggregateByDayOut(**d) for d in by_day_with_cum],
        by_stock=[
            AggregateByStockOut(
                stock_code=r["stock_code"],
                trade_count=r["trade_count"],
                realized_pnl=r["realized_pnl"],
                buy_amount=r["buy_amount"],
                sell_amount=r["sell_amount"],
            )
            for r in by_stock_rows
        ],
    )


# ──────── Helpers ────────

def _query_positions_dict() -> dict:
    """当前 Position 快照（按 stock_code 主键）

    v81.4 tables-migration: Positions.query_all() — positions 表行数小 (持仓数 ≤ 几十),
    直接全表读, 内存建 dict 索引.
    """
    pos_list = Positions.query_all()
    return {p.stock_code: p for p in pos_list}


def _today_str() -> str:
    from datetime import datetime
    return datetime.now().strftime("%Y%m%d")