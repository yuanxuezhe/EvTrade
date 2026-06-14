"""
t0_stats.py — T0 当日 / 历史收益汇总

GET /api/orders/t0-stats/{stock_code}?trading_day=YYYYMMDD
  返:
  {
    trd_date, stock_code, cost_basis, today_bought, today_sold,
    today_bought_amount, today_sold_amount, realized_pnl,
    position_volume, position_cost, current_market_value, unrealized_pnl,
    total_pnl, return_rate
  }
"""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel
from typing import List, Optional

from db import get_db
from models.orm import Order, Trade, Position, TradingDay
from auth.deps import get_current_user
from models.user import User
from services.guards import resolve_default_trd_date

router = APIRouter()


class T0StatsOut(BaseModel):
    TRD_DATE: str
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
    position_volume: int          # 当前持仓量（available + frozen）
    position_cost_total: float    # 持仓成本总额 = cost * volume
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
    trading_day: Optional[str] = Query(None, description="8 位数字 YYYYMMDD，默认激活日"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """T0 当日 + 历史收益汇总（单标的）"""
    trd_date = trading_day or resolve_default_trd_date(db)
    if not trd_date:
        raise HTTPException(
            status_code=400,
            detail={"code": "NO_TRADING_DAY", "msg": "无交易日，请先在系统初始化页激活"}
        )

    # 当日委托 / 成交
    orders_today = db.query(Order).filter(
        Order.TRD_DATE == trd_date,
        Order.stock_code == stock_code,
    ).all()
    trades_today = db.query(Trade).filter(
        Trade.TRD_DATE == trd_date,
        Trade.stock_code == stock_code,
    ).all()

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

    # 已实现盈亏（FIFO 简化：买入先入 → 卖出按当日买入均价匹配）
    # 真正的 T0 是先买后卖同股，盈亏 = (卖价 - 买价) × 配对股数
    # 简化：取当日买均价为基准
    if today_buy_vol > 0 and today_sell_vol > 0:
        avg_buy = today_buy_amt / today_buy_vol
        # 已实现 = 卖出股数 × (卖均价 - 买均价)
        avg_sell = today_sell_amt / today_sell_vol
        # 配对股数 = min(买,卖)
        paired = min(today_buy_vol, today_sell_vol)
        realized = (avg_sell - avg_buy) * paired
    else:
        realized = 0.0

    # 持仓
    pos = db.query(Position).filter(
        Position.TRD_DATE == trd_date,
        Position.stock_code == stock_code,
    ).first()
    cost_basis = float(pos.cost) if pos else 0.0
    position_vol = int(pos.total) if pos and pos.total else 0
    position_cost_total = cost_basis * position_vol

    # 浮动盈亏：取今日卖出均价比持仓成本（口径：若今日有卖，按"今日对锁"算）
    if today_sell_vol > 0:
        avg_sell = today_sell_amt / today_sell_vol
        # 卖出部分相对持仓成本的盈亏
        unrealized = (avg_sell - cost_basis) * min(today_sell_vol, position_vol) if cost_basis > 0 else 0
    else:
        unrealized = 0.0

    # 委托统计
    order_count = len(orders_today)
    open_order_count = sum(1 for o in orders_today if o.status in ("48", "49", "50"))

    return T0StatsOut(
        TRD_DATE=trd_date,
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
