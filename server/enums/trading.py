"""
trading.py — 交易协议枚举（与 XtQuant 柜台协议保持一致）

从原 server/constants.py 拆分出来，按语义归类。
"""


# ================================================================
# 价格类型 (price_type)
# ================================================================
class PriceType:
    """价格类型枚举

    v__: 与 xtconstant 柜台协议 1:1 对齐 (从原 5/11/14/44 4 选简化为 0/1/2 3 选)

      - FIX_PRICE = 0                       xtconstant.FIX_PRICE
      - LATEST_PRICE = 1                    xtconstant.LATEST_PRICE
      - MARKET_PEER_PRICE_FIRST = 2         xtconstant.MARKET_PEER_PRICE_FIRST
                                            (对手方最优价 / 吃档 1)

    旧码点 (5/11/14/44) 通过 ``2026-07-15-remap-price-type.py`` 迁移脚本
    自动映射: 11/14 → 0 (限价), 5 → 1 (最新价), 44 → 2 (市价)
    """
    FIX_PRICE = 0                    # 限价 (指定价)
    LATEST_PRICE = 1                 # 最新价
    MARKET_PEER_PRICE_FIRST = 2      # 市价 (对手方最优价, 吃档 1)

    _LABEL = {
        0: "限价",
        1: "最新价",
        2: "市价",
    }

    @classmethod
    def label(cls, code: int) -> str:
        return cls._LABEL.get(code, str(code))

    @classmethod
    def default(cls) -> int:
        return cls.FIX_PRICE


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
