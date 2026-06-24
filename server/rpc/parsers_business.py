"""
parsers_business.py — 业务特定响应解析器

每个 _parse_* 解析器统一返回 {"code": int, "msg": str, "list": list}：
  - code != 0 时 list 直接为空，不读第二结果集
  - code == 0 时按各业务字段映射规则解析第二结果集，list 为业务对象数组

提供：
- _parse_asset: 资金查询
- _parse_orders: 委托查询
- _parse_trades: 成交查询
- _parse_positions: 持仓查询
- _parse_order_ack: 下单 / 撤单 应答
"""
from typing import Any, Dict

from msgpacket import MsgPacket

from server.rpc.parsers_common import (
    _empty,
    _iter_rows,
    _parse_code_msg,
    _to_float,
    _to_int,
)


def _parse_asset(pkt: MsgPacket) -> Dict[str, Any]:
    """解析资金查询结果 → {code, msg, list:[{cash, frozen_cash, market_value, total_asset}]}"""
    code, msg = _parse_code_msg(pkt)
    if code != 0:
        return _empty(code, msg)
    items = []
    for row in _iter_rows(pkt, 2):
        items.append({
            "cash": _to_float(row.get("cash", "")),
            "frozen_cash": _to_float(row.get("frozen_cash", "")),
            "market_value": _to_float(row.get("market_value", "")),
            "total_asset": _to_float(row.get("total_asset", "")),
        })
    return {"code": code, "msg": msg, "list": items}


def _parse_orders(pkt: MsgPacket) -> Dict[str, Any]:
    """解析委托查询结果 → {code, msg, list:[order_dict, ...]}"""
    code, msg = _parse_code_msg(pkt)
    if code != 0:
        return _empty(code, msg)
    items = []
    for row in _iter_rows(pkt, 2):
        volume = row.get("order_volume") or row.get("volume") or "0"
        status = row.get("order_status") or row.get("status") or ""
        items.append({
            "order_id": row.get("order_id", ""),
            "stock_code": row.get("stock_code", ""),
            # 柜台 order_type 数字串：股票 23=买入，24=卖出
            "order_type": _to_int(row.get("order_type", "")),
            "price_type": _to_int(row.get("price_type", "")),
            "price": _to_float(row.get("price", "")),
            "volume": _to_int(volume),
            "traded_volume": _to_int(row.get("traded_volume", "")),
            "traded_price": _to_float(row.get("traded_price", "")),
            "status": status,
            "order_time": row.get("order_time", ""),
            "order_remark": row.get("order_remark", ""),
            "status_msg": row.get("status_msg", ""),
        })
    return {"code": code, "msg": msg, "list": items}


def _parse_trades(pkt: MsgPacket) -> Dict[str, Any]:
    """解析成交查询结果 → {code, msg, list:[trade_dict, ...]}"""
    code, msg = _parse_code_msg(pkt)
    if code != 0:
        return _empty(code, msg)
    items = []
    for row in _iter_rows(pkt, 2):
        volume = row.get("volume") or row.get("traded_volume") or "0"
        price = row.get("price") or row.get("traded_price") or "0"
        # 柜台报文字段名是 traded_id / traded_time；保留 trade_id / trade_time 作兼容
        items.append({
            "trade_id": row.get("traded_id", ""),
            "order_id": row.get("order_id", ""),
            "stock_code": row.get("stock_code", ""),
            # 柜台 order_type 数字串：股票 23=买入，24=卖出
            "order_type": row.get("order_type", ""),
            "volume": _to_int(volume),
            "price": _to_float(price),
            "trade_time": row.get("traded_time", ""),
        })
    return {"code": code, "msg": msg, "list": items}


def _parse_positions(pkt: MsgPacket) -> Dict[str, Any]:
    """解析持仓查询结果 → {code, msg, list:[pos_dict, ...]}"""
    code, msg = _parse_code_msg(pkt)
    if code != 0:
        return _empty(code, msg)
    items = []
    for row in _iter_rows(pkt, 2):
        volume = row.get("volume", "0")
        available = row.get("avl_amt") or row.get("available") or "0"
        cost = row.get("avg_price") or row.get("cost") or "0"
        market_value = row.get("market_value", "0")
        last_vol = row.get("last_vol", "0")
        items.append({
            "stock_code": row.get("stock_code", ""),
            "last_vol": _to_int(last_vol),
            "volume": _to_int(volume),
            "available": _to_int(available),
            "cost": _to_float(cost),
            "market_value": _to_float(market_value),
        })
    return {"code": code, "msg": msg, "list": items}


def _parse_order_ack(pkt: MsgPacket) -> Dict[str, Any]:
    """解析下单应答 → {code, msg, list:[ack_dict, ...]}

    第二结果集字段未严格约定（可能包含 order_id / order_sysid 等），
    这里原样透传 dict，由前端展示层处理。
    """
    code, msg = _parse_code_msg(pkt)
    if code != 0:
        return _empty(code, msg)
    return {"code": code, "msg": msg, "list": _iter_rows(pkt, 2)}
