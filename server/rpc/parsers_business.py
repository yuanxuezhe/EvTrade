"""
parsers_business.py — 业务特定响应解析器（v10 字段名约定：broker 原字段名）

每个 _parse_* 解析器统一返回 {"code": int, "msg": str, "list": list}：
  - code != 0 时 list 直接为空，不读第二结果集
  - code == 0 时按各业务字段映射规则解析第二结果集，list 为业务对象数组

v10 关键变更（rpc-field-alignment-ts-unify）：
- **保留 broker 原始字段名**（snake_case，`traded_id`/`avl_amt`/`avg_price`/`order_status` 等）
- 之前 parsers 内部把 `traded_id`→`trade_id`、`avl_amt`→`available` 等重命名，**改回 broker 原字段名**
- 内部命名映射（broker 字段名 → DB / API 字段名）由**调用方**（reconcile / api/）显式完成

权威源：`iquant/xtquant_api.py` 第 130-200 行（query handler）。

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
    """解析资金查询结果 → {code, msg, list:[{account_id, cash, frozen_cash, market_value, total_asset}]}

    v10: 透传 broker 原字段 `account_id`（之前丢弃；reconcile 不需要 account_id 但字段透传便于审计）
    """
    code, msg = _parse_code_msg(pkt)
    if code != 0:
        return _empty(code, msg)
    items = []
    for row in _iter_rows(pkt, 2):
        items.append({
            "account_id": row.get("account_id", ""),
            "cash": _to_float(row.get("cash", "")),
            "frozen_cash": _to_float(row.get("frozen_cash", "")),
            "market_value": _to_float(row.get("market_value", "")),
            "total_asset": _to_float(row.get("total_asset", "")),
        })
    return {"code": code, "msg": msg, "list": items}


def _parse_orders(pkt: MsgPacket) -> Dict[str, Any]:
    """解析委托查询结果 → {code, msg, list:[order_dict, ...]}

    v10 字段名（broker 原字段）：
      order_id / stock_code / order_type / price_type / price / order_volume /
      traded_volume / traded_price / order_status / status_msg / strategy_name /
      order_remark / order_time

    之前别名 `status`/`volume` 已废弃，调用方读 `order_status`/`order_volume`。
    """
    code, msg = _parse_code_msg(pkt)
    if code != 0:
        return _empty(code, msg)
    items = []
    for row in _iter_rows(pkt, 2):
        items.append({
            "order_id": row.get("order_id", ""),
            "stock_code": row.get("stock_code", ""),
            # 柜台 order_type 数字串：股票 23=买入，24=卖出
            "order_type": row.get("order_type", ""),
            "price_type": _to_int(row.get("price_type", "")),
            "price": _to_float(row.get("price", "")),
            "order_volume": _to_int(row.get("order_volume", "")),
            "traded_volume": _to_int(row.get("traded_volume", "")),
            "traded_price": _to_float(row.get("traded_price", "")),
            "order_status": row.get("order_status", ""),
            "status_msg": row.get("status_msg", ""),
            "strategy_name": row.get("strategy_name", ""),
            "order_remark": row.get("order_remark", ""),
            "order_time": row.get("order_time", ""),
        })
    return {"code": code, "msg": msg, "list": items}


def _parse_trades(pkt: MsgPacket) -> Dict[str, Any]:
    """解析成交查询结果 → {code, msg, list:[trade_dict, ...]}

    v10 字段名（broker 原字段）：
      order_id / traded_id / stock_code / order_type / traded_volume /
      traded_price / traded_amount / strategy_name / order_remark / traded_time

    之前别名 `trade_id`/`trade_time`/`volume`/`price` 已废弃，调用方读 `traded_id`/`traded_time`/`traded_volume`/`traded_price`。
    `traded_amount` / `strategy_name` / `order_remark` 之前丢弃，v10 起透传。
    """
    code, msg = _parse_code_msg(pkt)
    if code != 0:
        return _empty(code, msg)
    items = []
    for row in _iter_rows(pkt, 2):
        items.append({
            "order_id": row.get("order_id", ""),
            "traded_id": row.get("traded_id", ""),
            "stock_code": row.get("stock_code", ""),
            "order_type": row.get("order_type", ""),
            "traded_volume": _to_int(row.get("traded_volume", "")),
            "traded_price": _to_float(row.get("traded_price", "")),
            "traded_amount": _to_float(row.get("traded_amount", "")),
            "strategy_name": row.get("strategy_name", ""),
            "order_remark": row.get("order_remark", ""),
            "traded_time": row.get("traded_time", ""),
        })
    return {"code": code, "msg": msg, "list": items}


def _parse_positions(pkt: MsgPacket) -> Dict[str, Any]:
    """解析持仓查询结果 → {code, msg, list:[pos_dict, ...]}

    v10 字段名（broker 原字段）：
      stock_code / last_vol / volume / avl_amt / avg_price / market_value

    之前别名 `available`/`cost` 已废弃，调用方读 `avl_amt`/`avg_price`。
    """
    code, msg = _parse_code_msg(pkt)
    if code != 0:
        return _empty(code, msg)
    items = []
    for row in _iter_rows(pkt, 2):
        items.append({
            "stock_code": row.get("stock_code", ""),
            "last_vol": _to_int(row.get("last_vol", "")),
            "volume": _to_int(row.get("volume", "")),
            "avl_amt": _to_int(row.get("avl_amt", "")),
            "avg_price": _to_float(row.get("avg_price", "")),
            "market_value": _to_float(row.get("market_value", "")),
        })
    return {"code": code, "msg": msg, "list": items}


def _parse_order_ack(pkt: MsgPacket) -> Dict[str, Any]:
    """解析下单应答 → {code, msg, list:[ack_dict, ...]}

    第二结果集字段未严格约定（可能包含 order_id / order_sysid / seq 等），
    这里原样透传 dict，由前端展示层处理。
    """
    code, msg = _parse_code_msg(pkt)
    if code != 0:
        return _empty(code, msg)
    return {"code": code, "msg": msg, "list": _iter_rows(pkt, 2)}
