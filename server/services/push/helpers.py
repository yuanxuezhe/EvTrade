"""
push/helpers.py — 4 个 push handler 共用的小工具

提供：
- _str / _float / _int: 安全类型转换（broker 字段可能为 None / 字符串 / 缺失）
- 时间工具 re-export: _utcnow / TS_FMT / format_ts / parse_broker_ts / format_db_dt

时间戳权威位置在 server/utils/time.py。
"""
from typing import Any, Optional

# 时间工具（权威位置在 server/utils/time.py）


def _str(v: Any, default: str = '') -> str:
    """安全取字符串值"""
    if v is None:
        return default
    return str(v)


def _float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _order_to_out_dict(order) -> Optional[dict]:
    """ORM Order → OrderOut 兼容 dict（WS 推送用）"""
    if order is None:
        return None
    return {
        "order_id": _str(order.order_id or ''),
        "user_def": _str(order.user_def or ''),
        "order_no": _str(order.order_no),
        "trd_date": _str(order.trd_date),
        "stock_code": _str(order.stock_code),
        "order_type": _str(order.order_type),
        "price_type": _int(order.price_type, 0),
        "price": _float(order.price),
        "volume": _int(order.volume),
        "traded_volume": _int(order.traded_volume or 0),
        "traded_amount": _float(order.traded_amount or 0),
        "avg_price": _float(order.avg_price or 0),
        "cancelled_volume": _int(order.cancelled_volume or 0),
        "order_flag": _int(order.order_flag or 0),
        "status": _str(order.status),
        "status_msg": _str(order.status_msg or ''),
        "order_time": _str(order.order_time or ''),
        # v63: task_id 字段 (供 T0Trade 委托筛选, 之前为 null)
        "task_id": _int(order.task_id) if order.task_id is not None else None,
        # v66: strategy_type 字段 (REQ-TRADE-026; 0=普通单 1=快速做T)
        #   兜底 0: 历史单 ORM 列刚加, query 出 None 也按 0 处理
        "strategy_type": _int(order.strategy_type) if order.strategy_type is not None else 0,
    }


def _trade_to_out_dict(trade) -> Optional[dict]:
    """ORM Trade → TradeOut 兼容 dict（WS 推送用）"""
    if trade is None:
        return None
    return {
        "trade_id": _str(trade.trade_id),
        "trd_date": _str(trade.trd_date),
        "order_no": _str(trade.order_no),
        "stock_code": _str(trade.stock_code),
        "order_type": _str(trade.order_type),
        "price": _float(trade.price),
        "volume": _int(trade.volume),
        "amount": _float(trade.amount),
        "trade_time": _str(trade.trade_time or ''),
        "trade_type": _int(trade.trade_type or 0),
    }
