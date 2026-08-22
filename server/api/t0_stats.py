"""
t0_stats.py — T0 单标的统计（真实已实现算法）

GET /api/orders/t0-stats/{stock_code}?trd_date=YYYYMMDD   单日统计
GET /api/orders/t0-history/{stock_code}?days=30            历史曲线

算法语义：
- realized_pnl 用 t0_aggregate.calc_realized_pnl（真实算法）
  = (avg_sell - cost_basis) * sell_vol - commission - stamp_tax
  （非毛流差额，含持仓成本基准和费用）
- unrealized_pnl 基于当前持仓（position_vol × cost_basis），不叠加当日已实现
  = (avg_sell - cost_basis) * position_vol  // 持仓浮动（用当日卖出均价作为市场价近似）

实现要点：
- 无 Depends(get_db)；Orders/Trades/Positions 走 tables API (query_by/query_all) + 内存过滤
"""
from collections import defaultdict
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import List, Optional

from server.infra.db import db_session
from server.auth.deps import get_current_user
from server.services.guards import resolve_default_trd_date
from server.services.t0 import get_fee_config
from server.services.t0.aggregate_api import calc_realized_pnl
from server.services.t0.aggregators import resolve_t0_user_defs
from server.tables import Orders, Trades, Positions, Row

router = APIRouter()


class T0StatsOut(BaseModel):
    trd_date: str
    stock_code: str
    # 当日累计
    today_buy_volume: int
    today_sell_volume: int
    today_buy_amount: float       # sum(price * volume) for buys
    today_sell_amount: float      # sum(price * volume) for sells
    # 已实现盈亏
    realized_pnl: float
    # 持仓基准
    cost_basis: float             # 当前持仓的平均成本价
    position_volume: int          # 当前持仓量（avl_vol + frozen）
    position_cost_total: float    # 持仓成本总额 = cost_price * vol
    # 浮动盈亏（按当前持仓成本算，不算今日已实现的）
    unrealized_pnl: float         # = (avg_sell_price - cost_basis) * today_sell_volume
    # 汇总
    total_pnl: float              # realized + unrealized
    # 委托/成交
    order_count: int
    trade_count: int
    open_order_count: int


@router.get("/t0-stats/{stock_code}", response_model=T0StatsOut)
async def t0_stats(
    stock_code: str,
    trd_date: Optional[str] = Query(None, description="8 位数字 YYYYMMDD，默认激活日"),
    t0_only: bool = Query(False, description="只统计 user_def='T0' 标记的委托/成交"),
    user: Row = Depends(get_current_user),
):
    """T0 当日 + 历史收益汇总（单标的）

    Orders.query_by('trd_date', trd) + 内存过滤 stock_code/user_def;
    Positions.query_by('stock_code', stock_code).
    """
    # resolve_default_trd_date / resolve_t0_user_defs 仍需 db session (service 层保留 ORM)
    #   用 db_session() context manager (auto commit/close)
    with db_session() as db:
        trd = trd_date or resolve_default_trd_date(db)
    if not trd:
        raise HTTPException(
            status_code=400,
            detail={"code": "NO_TRADING_DAY", "msg": "无交易日，请先在系统初始化页激活"}
        )

    # 当日委托 / 成交 — 走 Orders.query_by('trd_date', trd) + 内存过滤 stock_code
    all_orders_today = Orders.query_by("trd_date", trd)
    orders_today = [o for o in all_orders_today if o.stock_code == stock_code]

    if t0_only:
        # T0 扩展：user_def='T0' literal + 所有 type='t0' 策略的 user_def（task 8）
        with db_session() as db:
            allowed = resolve_t0_user_defs(db, "T0")
        allowed_set = set(allowed) if allowed else set()
        orders_today = [o for o in orders_today if (o.user_def or "") in allowed_set]

    all_trades_today = Trades.query_by("trd_date", trd)
    trades_today = [t for t in all_trades_today if t.stock_code == stock_code]

    if t0_only:
        # 通过关联本地委托来过滤成交
        t0_order_nos = {o.order_no for o in orders_today}
        if t0_order_nos:
            trades_today = [t for t in trades_today if t.order_no in t0_order_nos]
        else:
            trades_today = []  # 强制空

    today_buy_vol = 0
    today_sell_vol = 0
    today_buy_amt = 0.0
    today_sell_amt = 0.0
    for t in trades_today:
        vol = int(t.volume or 0)
        price = float(t.price or 0)
        if t.order_type == "23":  # 买
            today_buy_vol += vol
            today_buy_amt += price * vol
        elif t.order_type == "24":  # 卖
            today_sell_vol += vol
            today_sell_amt += price * vol

    # 持仓（按 stock_code PK 单行）
    pos_rows = Positions.query_by("stock_code", stock_code)
    pos = pos_rows[0] if pos_rows else None
    cost_basis = float(pos.cost_price) if pos else 0.0
    position_vol = int(pos.vol) if pos and pos.vol else 0
    position_cost_total = cost_basis * position_vol

    # 已实现盈亏（真实算法：基于持仓成本基准 + 卖出方向费用）
    # 算法见 services.t0.aggregate_api.calc_realized_pnl
    sell_trades_today = [t for t in trades_today if t.order_type == "24"]
    fee_cfg = get_fee_config()
    realized, _commission, _stamp_tax = calc_realized_pnl(
        sell_trades_today, cost_basis, fee_cfg
    )

    # 浮动盈亏（基于当前持仓 × 持仓成本基准，用当日卖出均价作为市场价近似）
    #   - 不包含当日已实现（已用 realized_pnl 单独返回）
    #   - 持仓 vol=0 时无浮动盈亏
    if today_sell_vol > 0 and position_vol > 0:
        avg_sell = today_sell_amt / today_sell_vol
        unrealized = (avg_sell - cost_basis) * position_vol if cost_basis > 0 else 0.0
    elif today_sell_vol == 0 and position_vol > 0 and cost_basis > 0:
        # 当日无卖出但有持仓：用 0 作为市场价近似（亏全）
        # 实际应传最新价；当前 Position 表无最新价字段，此处保守返回 0 让前端用 quote
        unrealized = 0.0
    else:
        unrealized = 0.0

    # 委托统计
    order_count = len(orders_today)
    open_order_count = sum(1 for o in orders_today if (o.status or "") in ("48", "49", "50"))

    return T0StatsOut(
        trd_date=trd,
        stock_code=stock_code,
        today_buy_volume=today_buy_vol,
        today_sell_volume=today_sell_vol,
        today_buy_amount=round(today_buy_amt, 2),
        today_sell_amount=round(today_sell_amt, 2),
        realized_pnl=round(realized, 2),
        cost_basis=cost_basis,
        position_volume=position_vol,
        position_cost_total=round(position_cost_total, 2),
        unrealized_pnl=round(unrealized, 2),
        total_pnl=round(realized + unrealized, 2),
        order_count=order_count,
        trade_count=len(trades_today),
        open_order_count=open_order_count,
    )


# ============== T0 历史曲线 ==============

class T0HistoryPoint(BaseModel):
    trd_date: str
    realized_pnl: float
    sell_amount: float
    buy_amount: float
    trade_count: int


class T0HistoryOut(BaseModel):
    stock_code: str
    days: int
    points: List[T0HistoryPoint]
    total_realized: float
    total_return_rate: float
    win_days: int
    total_days: int


@router.get("/t0-history/{stock_code}", response_model=T0HistoryOut)
def t0_history(
    stock_code: str,
    days: int = Query(30, ge=1, le=180),
    t0_only: bool = Query(False, description="只统计 user_def='T0' 标记的成交"),
    user: Row = Depends(get_current_user),
):
    """近 N 天做T 每日买入/卖出/笔数 + 累计差额

    Trades.query_all() + 内存过滤 (区间 + 多条件 + IN, API 层不支持; 数据量小).
    """
    today = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=days * 2)).strftime("%Y%m%d")
    all_trades = Trades.query_all()
    q = [t for t in all_trades
         if t.stock_code == stock_code
         and (t.trd_date or "") >= start
         and (t.trd_date or "") <= today]

    if t0_only:
        # T0 扩展：user_def='T0' literal + 所有 type='t0' 策略的 user_def（task 8）
        with db_session() as db:
            allowed = resolve_t0_user_defs(db, "T0")
        allowed_set = set(allowed) if allowed else set()
        all_orders = Orders.query_all()
        t0_order_nos = {o.order_no for o in all_orders if (o.user_def or "") in allowed_set}
        if t0_order_nos:
            q = [t for t in q if t.order_no in t0_order_nos]
        else:
            q = []
    rows = q
    by_day = defaultdict(lambda: {
        "buy_amt": 0.0, "sell_amt": 0.0, "diff": 0.0, "n": 0
    })
    for t in rows:
        d = t.trd_date
        amt = float(t.amount or 0)
        if t.order_type == "23":  # 买
            by_day[d]["buy_amt"] += amt
            by_day[d]["diff"] -= amt  # 净流出
        elif t.order_type == "24":  # 卖
            by_day[d]["sell_amt"] += amt
            by_day[d]["diff"] += amt  # 净流入
        by_day[d]["n"] += 1
    points = []
    for d in sorted(by_day.keys()):
        info = by_day[d]
        points.append(T0HistoryPoint(
            trd_date=d,
            realized_pnl=round(info["diff"], 2),
            sell_amount=round(info["sell_amt"], 2),
            buy_amount=round(info["buy_amt"], 2),
            trade_count=info["n"],
        ))
    total_realized = sum(p.realized_pnl for p in points)
    win_days = sum(1 for p in points if p.realized_pnl > 0)
    total_buy = sum(p.buy_amount for p in points) or 1.0
    total_return_rate = total_realized / total_buy
    return T0HistoryOut(
        stock_code=stock_code,
        days=days,
        points=points,
        total_realized=round(total_realized, 2),
        total_return_rate=round(total_return_rate, 4),
        win_days=win_days,
        total_days=len(points),
    )
