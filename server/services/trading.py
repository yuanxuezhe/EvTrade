from typing import Dict, List, Optional
from datetime import datetime
from models.types import Position, Order, Trade, Asset

# 内存存储（第一版使用内存，后续迁移到数据库）
positions_store: Dict[str, Position] = {}
orders_store: List[Order] = []
trades_store: List[Trade] = []
asset_store = Asset()

def get_positions() -> List[Position]:
    return list(positions_store.values())

def get_position(stock_code: str) -> Optional[Position]:
    return positions_store.get(stock_code)

def init_position(stock_code: str) -> Position:
    pos = positions_store.get(stock_code)
    if pos:
        pos.initial_position = pos.total
        pos.today_buy = 0
        pos.today_sell = 0
    return pos

def update_position_from_trade(trade: Trade):
    pos = positions_store.get(trade.stock_code)
    if not pos:
        pos = Position(stock_code=trade.stock_code, stock_name="")
        positions_store[trade.stock_code] = pos

    if trade.direction == "BUY":
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
    return asset_store

def update_asset(asset: Asset):
    global asset_store
    asset_store = asset