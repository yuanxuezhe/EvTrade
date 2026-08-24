"""
server/ai/tools.py — EvTrade 业务调用的 MCP tool 实现

每 tool 一个函数, 签名: def tool_xxx(args: dict) -> dict
被 mcp_server.py 在 tools/call 路由里 dispatch.

设计:
    - 进程内直接调 server.tables.* / server.services.* / server.repo.*
      (FastAPI 进程内调用, 不走 HTTP, 不用 user JWT — 同 claudedemo 设计)
    - 纯函数, 无状态, 不缓存. 一次 tool call = 一次 DB query
    - 错误统一抛 ValueError / KeyError, mcp_server 转 isError=True
    - 字段名统一 snake_case (与 EvTrade REST API 一致)
    - inputSchema 见 schema() 函数, 单点维护, 与 handler 配对
"""
from __future__ import annotations

from typing import Any

from server.tables import Assets, Orders, Positions, Stocks, Trades, Users


# ────────────────────────────────────────────────────────────────────────
# 1. list_positions — 当前持仓 (MySQL positions 表, 展示源)
# ────────────────────────────────────────────────────────────────────────
def tool_list_positions(args: dict) -> dict:
    rows = Positions.query_all(order="desc") or []
    out = []
    for r in rows:
        cost = float(getattr(r, "cost_price", 0) or 0)
        vol = int(getattr(r, "vol", 0) or 0)
        out.append({
            "stock_code": getattr(r, "stock_code", ""),
            "stock_name": getattr(r, "stock_name", ""),
            "volume": vol,
            "available_volume": int(getattr(r, "avl_vol", 0) or 0),
            "cost_price": cost,
            # positions 表无 market_value 列; 按 cost_price * vol 估算 (与 REST 端点逻辑一致)
            "market_value": round(cost * vol, 2),
            "synced_at": str(getattr(r, "synced_at", "") or ""),
        })
    return {"positions": out, "count": len(out)}


def schema_list_positions() -> dict:
    return {
        "name": "list_positions",
        "description": (
            "查询当前持仓列表 (MySQL positions 表, v118+ broker pos_push 同步结果). "
            "返回每只持仓的 stock_code / stock_name / volume / available_volume / "
            "cost_price / market_value / synced_at. 无参数."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    }


# ────────────────────────────────────────────────────────────────────────
# 2. get_asset — 当前资金 (MySQL assets 表, last_asset 字段保留昨收)
# ────────────────────────────────────────────────────────────────────────
def tool_get_asset(args: dict) -> dict:
    rows = Assets.query_all(order="desc") or []
    if not rows:
        return {"asset": None, "note": "assets 表为空 (可能未做日初 init)"}
    a = rows[0]
    return {
        "asset": {
            "cash": float(getattr(a, "cash", 0) or 0),
            "available": float(getattr(a, "available", 0) or 0),
            "frozen_cash": float(getattr(a, "frozen_cash", 0) or 0),
            "market_value": float(getattr(a, "market_value", 0) or 0),
            "total_asset": float(getattr(a, "total_asset", 0) or 0),
            "last_asset": float(getattr(a, "last_asset", 0) or 0),
            "synced_at": str(getattr(a, "synced_at", "") or ""),
        }
    }


def schema_get_asset() -> dict:
    return {
        "name": "get_asset",
        "description": (
            "查询当前资金状况 (MySQL assets 表). 返回 cash / available / frozen_cash / "
            "market_value / total_asset / last_asset (昨收总资产) / synced_at. "
            "last_asset > 0 且 total_asset = 0 表示未做日初. 无参数."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    }


# ────────────────────────────────────────────────────────────────────────
# 3. list_orders — 当日委托 (trd_date 参数, 默认激活日)
# ────────────────────────────────────────────────────────────────────────
def tool_list_orders(args: dict) -> dict:
    from server.services.sysconfig import _get_active_trd_date
    trd_date = args.get("trd_date") or _get_active_trd_date() or ""
    rows = Orders.query_by("trd_date", trd_date) or []
    return {
        "trd_date": trd_date,
        "orders": [
            {
                "order_no": str(getattr(r, "order_no", "") or ""),
                "stock_code": getattr(r, "stock_code", ""),
                "order_type": getattr(r, "order_type", ""),
                "price": float(getattr(r, "price", 0) or 0),
                "volume": getattr(r, "volume", 0) or 0,
                "status": getattr(r, "status", ""),
                "traded_volume": getattr(r, "traded_volume", 0) or 0,
            }
            for r in rows
        ],
        "count": len(rows),
    }


def schema_list_orders() -> dict:
    return {
        "name": "list_orders",
        "description": (
            "查询指定交易日委托列表 (MySQL orders 表). trd_date 不传则用激活日 (sys_status). "
            "返回 order_no / stock_code / order_type / price / volume / status / traded_volume."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "trd_date": {
                    "type": "string",
                    "description": "交易日 YYYYMMDD, 不传则用激活日",
                },
            },
        },
    }


# ────────────────────────────────────────────────────────────────────────
# 4. list_trades — 当日成交
# ────────────────────────────────────────────────────────────────────────
def tool_list_trades(args: dict) -> dict:
    from server.services.sysconfig import _get_active_trd_date
    trd_date = args.get("trd_date") or _get_active_trd_date() or ""
    rows = Trades.query_by("trd_date", trd_date) or []
    return {
        "trd_date": trd_date,
        "trades": [
            {
                "order_no": str(getattr(r, "order_no", "") or ""),
                "stock_code": getattr(r, "stock_code", ""),
                "price": float(getattr(r, "price", 0) or 0),
                "volume": getattr(r, "volume", 0) or 0,
                "trade_time": str(getattr(r, "trade_time", "") or ""),
            }
            for r in rows
        ],
        "count": len(rows),
    }


def schema_list_trades() -> dict:
    return {
        "name": "list_trades",
        "description": (
            "查询指定交易日成交列表 (MySQL trades 表). trd_date 不传则用激活日. "
            "返回 order_no / stock_code / price / volume / trade_time."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "trd_date": {"type": "string", "description": "交易日 YYYYMMDD, 不传则用激活日"},
            },
        },
    }


# ────────────────────────────────────────────────────────────────────────
# 5. list_users — 用户列表 (admin only 业务逻辑, tool 层不强制, 靠 system prompt 教育)
# ────────────────────────────────────────────────────────────────────────
def tool_list_users(args: dict) -> dict:
    rows = Users.query_all() or []
    return {
        "users": [
            {
                "id": getattr(r, "id", None),
                "username": getattr(r, "username", ""),
                "role": getattr(r, "role", ""),
                "is_active": bool(getattr(r, "is_active", False)),
                "full_name": getattr(r, "full_name", "") or "",
            }
            for r in rows
        ],
        "count": len(rows),
    }


def schema_list_users() -> dict:
    return {
        "name": "list_users",
        "description": (
            "查询系统所有用户 (users 表). 返回 id / username / role / is_active / full_name. "
            "敏感操作 (改密 / 改角色) 不在此 tool 范围, 提示用户走前端."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    }


# ────────────────────────────────────────────────────────────────────────
# 6. list_stocks — 股票池 (stocks 表, 只读, 用于上下文)
# ────────────────────────────────────────────────────────────────────────
def tool_list_stocks(args: dict) -> dict:
    keyword = args.get("keyword", "")
    if keyword:
        # query_by 简化版: 全字段扫 (生产环境量大时考虑 LIKE 索引)
        rows = Stocks.query_all() or []
        rows = [
            r for r in rows
            if keyword.lower() in (getattr(r, "stock_code", "") or "").lower()
            or keyword.lower() in (getattr(r, "stock_name", "") or "").lower()
        ]
    else:
        rows = Stocks.query_all() or []
    return {
        "stocks": [
            {
                "stock_code": getattr(r, "stock_code", ""),
                "stock_name": getattr(r, "stock_name", ""),
                "stktype": getattr(r, "stktype", 0) or 0,
                "scale": getattr(r, "scale", 2) or 2,
            }
            for r in rows[:200]  # 限 200 防 LLM 上下文爆
        ],
        "count": len(rows),
        "truncated": len(rows) > 200,
    }


def schema_list_stocks() -> dict:
    return {
        "name": "list_stocks",
        "description": (
            "查询股票池 (stocks 表). 可选 keyword 参数按 stock_code / stock_name 模糊匹配. "
            "返回 stock_code / stock_name / stktype / scale. 结果限 200 条."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "可选, 按代码或名称模糊匹配"},
            },
        },
    }


# ────────────────────────────────────────────────────────────────────────
# 7. ai_analysis — LLM 分析助手 (调现有 ai_analysis 内部函数, 复用 RPC + prompt)
# ────────────────────────────────────────────────────────────────────────
def tool_ai_analysis(args: dict) -> dict:
    """复用现有 ai_analysis 内部服务 (server/api/ai_analysis.py 的服务函数).

    注意: 这是「用 EvTrade 内置 LLM 分析」, 跟 claude -p 调 MCP 是不同层级.
    实际语义: agent 想让 EvTrade 内置 LLM 看一眼行情/委托/成交, 用这个 tool.
    """
    stock_code = args.get("stock_code", "")
    if not stock_code:
        raise ValueError("stock_code required")
    prompt = args.get("prompt", "")
    # 调 server.api.ai_analysis 的内部 async 函数 — 同步包装
    import asyncio
    from server.api.ai_analysis import ai_analysis_for_stock
    result = asyncio.run(ai_analysis_for_stock(stock_code=stock_code, prompt=prompt))
    return {"stock_code": stock_code, "analysis": result}


def schema_ai_analysis() -> dict:
    return {
        "name": "ai_analysis",
        "description": (
            "调 EvTrade 内置 LLM 分析指定股票 (复用现有 ai_analysis 内部服务). "
            "需要 stock_code, 可选 prompt (用户问题). 返回 analysis 文本."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "stock_code": {"type": "string", "description": "股票代码 (必填)"},
                "prompt": {"type": "string", "description": "可选问题/上下文"},
            },
            "required": ["stock_code"],
        },
    }


# ────────────────────────────────────────────────────────────────────────
# Registry — mcp_server 用
# ────────────────────────────────────────────────────────────────────────
TOOL_HANDLERS = {
    "list_positions": tool_list_positions,
    "get_asset": tool_get_asset,
    "list_orders": tool_list_orders,
    "list_trades": tool_list_trades,
    "list_users": tool_list_users,
    "list_stocks": tool_list_stocks,
    "ai_analysis": tool_ai_analysis,
}

TOOL_SCHEMAS = [
    schema_list_positions(),
    schema_get_asset(),
    schema_list_orders(),
    schema_list_trades(),
    schema_list_users(),
    schema_list_stocks(),
    schema_ai_analysis(),
]


def call(name: str, args: dict) -> Any:
    """mcp_server 调这里: dispatch tool by name. 抛 Exception 表示工具错误."""
    handler = TOOL_HANDLERS.get(name)
    if not handler:
        raise KeyError(f"unknown tool: {name!r}, available: {list(TOOL_HANDLERS)}")
    return handler(args or {})