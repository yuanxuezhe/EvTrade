"""
EvTrade 常量定义

所有业务常量应集中在这里定义，避免散落在多处导致维护困难。
"""

# ================================================================
# 价格类型 (price_type)
# 与 XtQuant 柜台协议保持一致
# ================================================================
class PriceType:
    """价格类型枚举"""
    # 柜台协议数字码
    LATEST = 5       # 最新价
    LIMIT = 11       # 指定价 (限价)
    OPPONENT = 14    # 挂单价 (对手价)
    MARKET = 44      # 市价

    # 人类可读标签
    _LABEL = {
        5: "最新价",
        11: "限价",
        14: "挂单价",
        44: "市价",
    }

    @classmethod
    def label(cls, code: int) -> str:
        """将代码转为标签，未知代码返回代码本身"""
        return cls._LABEL.get(code, str(code))

    @classmethod
    def default(cls) -> int:
        """默认价格类型（限价单）"""
        return cls.LIMIT


# ================================================================
# 订单类型 (order_type)
# 与 XtQuant 柜台协议保持一致
# ================================================================
class OrderType:
    """订单类型枚举"""
    BUY = "23"   # 买入
    SELL = "24"  # 卖出


# ================================================================
# 订单状态 (order status)
# 与前端 store 保持一致
# ================================================================
class OrderStatus:
    """订单状态枚举"""
    PENDING_REPORT = "48"    # 待报
    REPORTED = "49"          # 已报
    PARTIAL = "50"           # 部分成交
    CANCELLED = "51"         # 已撤
    FILLED = "52"            # 已成交
    REJECTED = "53"          # 已拒
    PENDING_CANCEL = "54"    # 撤单中
    PARTIAL_CANCEL = "55"    # 部分撤单
    FAILED = "55"            # RPC 失败
    UNKNOWN = "99"           # 未知

    _LABEL = {
        "48": "待报",
        "49": "已报",
        "50": "部分成交",
        "51": "已撤",
        "52": "已成交",
        "53": "已拒",
        "54": "撤单中",
        "55": "失败",
        "99": "未知",
    }

    @classmethod
    def label(cls, code: str) -> str:
        return cls._LABEL.get(code, code)

    @classmethod
    def is_terminal(cls, code: str) -> bool:
        """是否终态（不可再变）"""
        return code in ("51", "52", "53", "54", "55", "56")

    @classmethod
    def is_cancellable(cls, code: str) -> bool:
        """是否可撤单"""
        return code in ("48", "49")


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
