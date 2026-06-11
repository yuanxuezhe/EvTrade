from typing import Dict, List, Optional
from datetime import datetime
from models.types import Position, Order, Trade, Asset

# 内存存储（当日交易相关）
positions_store: Dict[str, Position] = {}
orders_store: List[Order] = []
trades_store: List[Trade] = []

# XtQuant交易器（全局单例）
_trader = None
_account = None


def set_trader(trader, account):
    """设置XtQuant交易器"""
    global _trader, _account
    _trader = trader
    _account = account


def get_trader():
    return _trader


def get_account():
    return _account


def get_positions() -> List[Position]:
    """获取持仓列表（含XtQuant实时持仓）"""
    positions = list(positions_store.values())

    # 如果有XtQuant交易器，查询实时持仓
    if _trader and _account:
        try:
            # XtQuant持仓查询...
            pass
        except Exception:
            pass

    return positions


def get_position(stock_code: str) -> Optional[Position]:
    return positions_store.get(stock_code)


def init_position(stock_code: str) -> Position:
    """日初初始化：将total设为新的initialPosition，重置todayBuy/todaySell"""
    pos = positions_store.get(stock_code)
    if pos:
        pos.initial_position = pos.total
        pos.today_buy = 0
        pos.today_sell = 0
    return pos


def update_position_from_trade(trade: Trade):
    """根据成交更新持仓的今日买卖"""
    pos = positions_store.get(trade.stock_code)
    if not pos:
        pos = Position(stock_code=trade.stock_code, stock_name="")
        positions_store[trade.stock_code] = pos

    # 股票 order_type：23=买入，24=卖出
    if trade.order_type == "23":
        pos.today_buy += trade.volume
    else:
        pos.today_sell += trade.volume


def add_order(order: Order):
    orders_store.append(order)


def get_orders(stock_code: Optional[str] = None) -> List[Order]:
    if stock_code:
        return [o for o in orders_store if o.stock_code == stock_code]
    return orders_store


def update_order_status(order_id: str, status: str, traded_volume: int = 0, traded_price: float = 0.0):
    for order in orders_store:
        if order.order_id == order_id:
            order.status = status
            order.traded_volume = traded_volume
            order.traded_price = traded_price
            break


def add_trade(trade: Trade):
    trades_store.append(trade)
    update_position_from_trade(trade)


def get_trades(stock_code: Optional[str] = None) -> List[Trade]:
    if stock_code:
        return [t for t in trades_store if t.stock_code == stock_code]
    return trades_store


def get_asset() -> Asset:
    """获取资金信息，优先从XtQuant查询"""
    if _trader and _account:
        try:
            asset = _trader.query_stock_asset(_account)
            if asset:
                return Asset(
                    cash=asset.cash,
                    frozen_cash=asset.frozen_cash,
                    market_value=asset.market_value,
                    total_asset=asset.total_asset
                )
        except Exception as e:
            print(f"query_stock_asset error: {e}")

    # fallback到内存
    return Asset(cash=0, frozen_cash=0, market_value=0, total_asset=0)