"""
types.py — 内存 dataclass 模型（用于 service 层无 DB 上下文场景）

2026-06-15 重构：字段对齐 v5 ORM
  - Order 移除 order_remark（broker 透传字段重名）
  - Position 字段重命名：last_vol / vol / avl_vol / cost_price
"""
from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime
from constants import PriceType

@dataclass
class Position:
    stock_code: str
    stock_name: str = ""
    last_vol: int = 0       # 期初持仓
    today_buy: int = 0
    today_sell: int = 0

    @property
    def avl_vol(self) -> int:
        """可用 = 期初 - 今日卖出 + 今日买入"""
        return self.last_vol - self.today_sell + self.today_buy

    @property
    def vol(self) -> int:
        """总持仓 = 期初 + 今日买入 - 今日卖出"""
        return self.last_vol + self.today_buy - self.today_sell

@dataclass
class Order:
    order_id: str
    stock_code: str
    # 柜台 order_type 数字串：股票 23=买入，24=卖出
    order_type: str
    volume: int
    price: float
    # 柜台 price_type 数字：5=最新价 11=指定价 (限价) 14=对手价 44=市价
    price_type: int = PriceType.LIMIT
    status: str = "pending"  # pending / filled / cancelled / rejected
    traded_volume: int = 0
    traded_price: float = 0.0
    order_time: str = ""
    # 柜台废单原因文本（终端态 status=57 时由柜台附带）
    # NOTE: order_remark 已移除（v5 重构）— broker 透传 order_no 走 RPC remark 字段
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
