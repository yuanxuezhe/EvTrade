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
    # 柜台 order_type 数字串：股票 23=买入，24=卖出
    order_type: str
    volume: int
    price: float
    # 柜台 price_type 数字：5=最新价 11=指定价 14=对手价 44=市价 ...
    price_type: int = 11
    status: str = "pending"  # pending / filled / cancelled / rejected
    traded_volume: int = 0
    traded_price: float = 0.0
    order_time: str = ""
    # 柜台返回的废单/撤单原因说明
    order_remark: str = ""
    # 柜台废单原因文本（终端态 status=57 时由柜台附带）
    status_msg: str = ""

@dataclass
class Trade:
    trade_id: str
    order_id: str
    stock_code: str
    # 柜台 order_type 数字串：股票 23=买入，24=卖出
    order_type: str
    volume: int
    price: float
    trade_time: str = ""

@dataclass
class Asset:
    cash: float = 0.0
    frozen_cash: float = 0.0
    market_value: float = 0.0
    total_asset: float = 0.0