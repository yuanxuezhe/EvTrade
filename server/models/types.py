from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime

@dataclass
class Position:
    stock_code: str
    stock_name: str = ""
    initial_position: int = 0
    today_buy: int = 0
    today_sell: int = 0

    @property
    def available(self) -> int:
        return self.initial_position - self.today_sell + self.today_buy

    @property
    def total(self) -> int:
        return self.initial_position + self.today_buy - self.today_sell

@dataclass
class Order:
    order_id: str
    stock_code: str
    direction: str  # BUY / SELL
    volume: int
    price: float
    price_type: str = "LIMIT"
    status: str = "pending"  # pending / filled / cancelled / rejected
    traded_volume: int = 0
    traded_price: float = 0.0
    order_time: str = ""

@dataclass
class Trade:
    trade_id: str
    order_id: str
    stock_code: str
    direction: str
    volume: int
    price: float
    trade_time: str = ""

@dataclass
class Asset:
    cash: float = 0.0
    frozen_cash: float = 0.0
    market_value: float = 0.0
    total_asset: float = 0.0