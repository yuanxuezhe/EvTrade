"""
EvTrade 常量定义（向后兼容 facade）

枚举已拆分到 server/enums/ 和 server/services/order_status.py。
此文件保留以兼容既有 import 路径。

v11 修订 (align-status-codes-to-xtconstant):
- 删 `OrderStatus` re-export (`Status` 类已删, 见 server/services/order_status.py)
"""
from server.enums.trading import PriceType, OrderType, Direction

__all__ = ["PriceType", "OrderType", "Direction"]