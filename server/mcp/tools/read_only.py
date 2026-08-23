"""
server/mcp/tools/read_only.py — 6 个只读 tool

| Tool | Toolset | 描述 |
|---|---|---|
| list_positions | read-only | 查当前用户的持仓 |
| get_asset | read-only | 查当前用户的资金 |
| list_orders | read-only | 查当前用户的今日委托 |
| list_trades | read-only | 查当前用户的今日成交 |
| get_quote | read-only | 查指定股票最新行情 |
| list_strategies | read-only | 查当前用户的策略脚本 |
"""
import logging
from typing import Optional

from .._client import EvTradeAPIError, call_evtrade
from .._jwt import JWTError, decode_user_id
from .._registry import register

log = logging.getLogger(__name__)


async def _list_positions(jwt_token: str) -> dict:
    """查当前用户的所有持仓."""
    user_id = decode_user_id(jwt_token)
    try:
        data = await call_evtrade(
            method="GET", path="/api/positions", jwt_token=jwt_token,
        )
    except EvTradeAPIError as e:
        return {"ok": False, "error": e.detail, "status_code": e.status_code}
    return {"ok": True, "user_id": user_id, "positions": data.get("list", data.get("positions", []))}


async def _get_asset(jwt_token: str) -> dict:
    """查当前用户的可用资金 + 总资产."""
    user_id = decode_user_id(jwt_token)
    try:
        data = await call_evtrade(
            method="GET", path="/api/asset", jwt_token=jwt_token,
        )
    except EvTradeAPIError as e:
        return {"ok": False, "error": e.detail, "status_code": e.status_code}
    return {"ok": True, "user_id": user_id, "asset": data}


async def _list_orders(
    jwt_token: str,
    trading_day: Optional[str] = None,
    status: Optional[str] = None,
) -> dict:
    """查当前用户的今日委托（按 trading_day 默认 = 激活日）.

    Args:
        trading_day: YYYYMMDD（可选；默认 = 服务端激活日）
        status: 委托状态过滤（可选；如 "filled" / "pending"）
    """
    user_id = decode_user_id(jwt_token)
    params = {}
    if trading_day:
        params["trading_day"] = trading_day
    if status:
        params["status"] = status
    try:
        data = await call_evtrade(
            method="GET", path="/api/orders", jwt_token=jwt_token, params=params,
        )
    except EvTradeAPIError as e:
        return {"ok": False, "error": e.detail, "status_code": e.status_code}
    return {"ok": True, "user_id": user_id, "orders": data.get("list", [])}


async def _list_trades(
    jwt_token: str,
    trading_day: Optional[str] = None,
    stock_code: Optional[str] = None,
) -> dict:
    """查当前用户的今日成交."""
    user_id = decode_user_id(jwt_token)
    params = {}
    if trading_day:
        params["trading_day"] = trading_day
    if stock_code:
        params["stock_code"] = stock_code
    try:
        data = await call_evtrade(
            method="GET", path="/api/trades", jwt_token=jwt_token, params=params,
        )
    except EvTradeAPIError as e:
        return {"ok": False, "error": e.detail, "status_code": e.status_code}
    return {"ok": True, "user_id": user_id, "trades": data.get("list", [])}


async def _get_quote(jwt_token: str, stock_code: str) -> dict:
    """查指定股票最新行情（last_price / volume / change_pct 等）.

    Args:
        stock_code: 股票代码, e.g. "600000.SH"
    """
    decode_user_id(jwt_token)  # 验证 JWT 即可，不强需 user_id
    try:
        data = await call_evtrade(
            method="GET",
            path=f"/api/quote/{stock_code}",
            jwt_token=jwt_token,
        )
    except EvTradeAPIError as e:
        return {"ok": False, "error": e.detail, "status_code": e.status_code}
    return {"ok": True, "quote": data}


async def _list_strategies(
    jwt_token: str,
    filter_mode: str = "mine",
) -> dict:
    """查当前用户的策略脚本.

    Args:
        filter_mode: "mine" / "public" / "all"
    """
    user_id = decode_user_id(jwt_token)
    try:
        data = await call_evtrade(
            method="GET",
            path="/api/script-strategy/scripts",
            jwt_token=jwt_token,
            params={"filter": filter_mode},
        )
    except EvTradeAPIError as e:
        return {"ok": False, "error": e.detail, "status_code": e.status_code}
    return {"ok": True, "user_id": user_id, "strategies": data.get("list", [])}


# ─── 注册到 TOOL_REGISTRY ─────────────────────────────────────────
register(
    name="list_positions",
    description="查询当前用户的所有持仓（包含股票代码、持仓数量、可卖数量、浮动盈亏等）",
    schema={
        "type": "object",
        "properties": {},
        "required": ["jwt_token"],
        "additionalProperties": False,
    },
    handler=_list_positions,
    high_risk=False,
    toolset="read-only",
)

register(
    name="get_asset",
    description="查询当前用户的可用资金、总资产、冻结金额、当日盈亏等资金信息",
    schema={
        "type": "object",
        "properties": {},
        "required": ["jwt_token"],
        "additionalProperties": False,
    },
    handler=_get_asset,
    high_risk=False,
    toolset="read-only",
)

register(
    name="list_orders",
    description="查询当前用户的今日委托（按 trading_day 默认 = 服务端激活日，可按 status 过滤）",
    schema={
        "type": "object",
        "properties": {
            "trading_day": {"type": "string", "description": "YYYYMMDD（可选）"},
            "status": {"type": "string", "description": "委托状态过滤（可选）"},
        },
        "required": ["jwt_token"],
        "additionalProperties": False,
    },
    handler=_list_orders,
    high_risk=False,
    toolset="read-only",
)

register(
    name="list_trades",
    description="查询当前用户的今日成交（按 trading_day 默认 = 服务端激活日，可按 stock_code 过滤）",
    schema={
        "type": "object",
        "properties": {
            "trading_day": {"type": "string", "description": "YYYYMMDD（可选）"},
            "stock_code": {"type": "string", "description": "股票代码（可选）"},
        },
        "required": ["jwt_token"],
        "additionalProperties": False,
    },
    handler=_list_trades,
    high_risk=False,
    toolset="read-only",
)

register(
    name="get_quote",
    description="查询指定股票的实时行情（最新价、涨跌额、涨跌幅、成交量等）",
    schema={
        "type": "object",
        "properties": {
            "stock_code": {"type": "string", "description": "股票代码, e.g. '600000.SH'"},
        },
        "required": ["jwt_token", "stock_code"],
        "additionalProperties": False,
    },
    handler=_get_quote,
    high_risk=False,
    toolset="read-only",
)

register(
    name="list_strategies",
    description="查询当前用户的策略脚本（默认 mine，可选 public/all）",
    schema={
        "type": "object",
        "properties": {
            "filter_mode": {
                "type": "string",
                "enum": ["mine", "public", "all"],
                "default": "mine",
            },
        },
        "required": ["jwt_token"],
        "additionalProperties": False,
    },
    handler=_list_strategies,
    high_risk=False,
    toolset="read-only",
)


# ─── import 时副作用 — 让 FastAPI agent.py 一 import 整个 mcp 包就拿到 6 个 tool
def register_all() -> None:
    """空函数 — 已通过模块顶层 register() 副作用完成。保留供 agent.py 显式调用"""
    pass
