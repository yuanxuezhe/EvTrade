"""
EvTrade 常量定义（向后兼容 facade）

枚举已拆分到 server/enums/ 和 server/services/order_status.py。
此文件保留以兼容既有 import 路径。
"""
from server.enums.trading import PriceType, OrderType, Direction
from server.services.order_status import Status as OrderStatus

__all__ = ["PriceType", "OrderType", "OrderStatus", "Direction"]
