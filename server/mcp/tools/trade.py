"""
server/mcp/tools/trade.py — 高危 trade tool（⚠️ 需前端二次确认）

| Tool | High Risk | Toolset | 描述 |
|---|---|---|---|
| place_order | ✅ | trade | 下单 |
| cancel_order | ✅ | trade | 撤单 |

**重要**：这两个 tool 直接调 EvTrade REST API（不返回 confirmation_required — confirmation 由 FastAPI agent gateway 在 tool 调用**之前**拦截，详见 REQ-ARCH-008 §二次确认协议）。

LLM 调用此 tool 时：MCP 层**直接执行**（因为 FastAPI gateway 已在前置拦截并确认）。
"""
import logging
from typing import Optional

from .._client import EvTradeAPIError, call_evtrade
from .._jwt import decode_user_id
from .._registry import register

log = logging.getLogger(__name__)


async def _place_order(
    jwt_token: str,
    stock_code: str,
    direction: str,
    price_type: str,
    price: float,
    volume: int,
    strategy_id: Optional[int] = None,
) -> dict:
    """下单（⚠️ 实际下单，已被 FastAPI gateway 二次确认）.

    Args:
        stock_code: 股票代码, e.g. "600000.SH"
        direction: "buy" / "sell"
        price_type: "limit" / "market"
        price: 限价单价格（市价单可传 0）
        volume: 委托数量（股，必须为 100 的整数倍）
        strategy_id: 关联策略 id（可选）
    """
    user_id = decode_user_id(jwt_token)
    body = {
        "stock_code": stock_code,
        "direction": direction,
        "price_type": price_type,
        "price": price,
        "volume": volume,
    }
    if strategy_id is not None:
        body["strategy_id"] = strategy_id
    try:
        data = await call_evtrade(
            method="POST",
            path="/api/orders",
            jwt_token=jwt_token,
            json_body=body,
        )
    except EvTradeAPIError as e:
        return {"ok": False, "error": e.detail, "status_code": e.status_code}
    return {"ok": True, "user_id": user_id, "order": data}


async def _cancel_order(
    jwt_token: str,
    order_no: str,
    trd_date: str,
) -> dict:
    """撤单（⚠️ 实际撤单，已被 FastAPI gateway 二次确认）.

    Args:
        order_no: 8 位数字委托编号
        trd_date: YYYYMMDD 交易日
    """
    user_id = decode_user_id(jwt_token)
    try:
        data = await call_evtrade(
            method="DELETE",
            path=f"/api/orders/{order_no}",
            jwt_token=jwt_token,
            params={"trd_date": trd_date},
        )
    except EvTradeAPIError as e:
        return {"ok": False, "error": e.detail, "status_code": e.status_code}
    return {"ok": True, "user_id": user_id, "cancel_result": data}


# ─── 注册 ─────────────────────────────────────────────────────────
register(
    name="place_order",
    description=(
        "⚠️ REQUIRES_USER_CONFIRMATION — 下单（买入或卖出）。"
        "实际执行前会由前端弹 Modal 让用户确认操作预览。"
        "返回委托详情（含 order_no / status）。"
    ),
    schema={
        "type": "object",
        "properties": {
            "stock_code": {"type": "string", "description": "股票代码, e.g. '600000.SH'"},
            "direction": {"type": "string", "enum": ["buy", "sell"]},
            "price_type": {"type": "string", "enum": ["limit", "market"]},
            "price": {"type": "number", "description": "限价单价格（市价单可传 0）"},
            "volume": {"type": "integer", "description": "委托数量（股，100 的整数倍）"},
            "strategy_id": {"type": "integer", "description": "关联策略 id（可选）"},
        },
        "required": ["jwt_token", "stock_code", "direction", "price_type", "volume"],
        "additionalProperties": False,
    },
    handler=_place_order,
    high_risk=True,
    toolset="trade",
)

register(
    name="cancel_order",
    description=(
        "⚠️ REQUIRES_USER_CONFIRMATION — 撤单。"
        "实际执行前会由前端弹 Modal 让用户确认。"
        "返回撤单结果。"
    ),
    schema={
        "type": "object",
        "properties": {
            "order_no": {"type": "string", "description": "8 位数字委托编号"},
            "trd_date": {"type": "string", "description": "YYYYMMDD 交易日"},
        },
        "required": ["jwt_token", "order_no", "trd_date"],
        "additionalProperties": False,
    },
    handler=_cancel_order,
    high_risk=True,
    toolset="trade",
)
