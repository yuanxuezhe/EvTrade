"""
trading.py — 交易协议枚举（与 XtQuant 柜台协议保持一致）

从原 server/constants.py 拆分出来，按语义归类。
"""


# ================================================================
# 价格类型 (price_type)
# ================================================================
class PriceType:
    """价格类型枚举"""
    LATEST = 5       # 最新价
    LIMIT = 11       # 指定价 (限价)
    OPPONENT = 14    # 挂单价 (对手价)
    MARKET = 44      # 市价

    _LABEL = {
        5: "最新价",
        11: "限价",
        14: "挂单价",
        44: "市价",
    }

    @classmethod
    def label(cls, code: int) -> str:
        return cls._LABEL.get(code, str(code))

    @classmethod
    def default(cls) -> int:
        return cls.LIMIT


# ================================================================
# 订单类型 (order_type)
# ================================================================
class OrderType:
    """订单类型枚举"""
    BUY = "23"   # 买入
    SELL = "24"  # 卖出


# ================================================================
# 交易方向 (direction)
# ================================================================
class Direction:
    """交易方向"""
    BUY = "BUY"
    SELL = "SELL"

    @classmethod
    def opposite(cls, d: str) -> str:
        return cls.SELL if d == cls.BUY else cls.BUY
