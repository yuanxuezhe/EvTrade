"""
server/mcp/tools/admin.py — 高危 admin tool（⚠️ 需前端二次确认）

| Tool | High Risk | Toolset | 描述 |
|---|---|---|---|
| delete_strategy_script | ✅ | admin | 删除策略脚本 |
| init_trading_day | ✅ | admin | 系统日初 |
| set_user_role | ✅ | admin | 改用户角色（暂未实现 — EvTrade 端点缺失；见 TODO） |
"""
import logging

from .._client import EvTradeAPIError, call_evtrade
from .._jwt import decode_user_id
from .._registry import register

log = logging.getLogger(__name__)


async def _delete_strategy_script(
    jwt_token: str,
    script_id: int,
) -> dict:
    """删除策略脚本（⚠️ 已被 FastAPI gateway 二次确认）."""
    user_id = decode_user_id(jwt_token)
    try:
        await call_evtrade(
            method="DELETE",
            path=f"/api/script-strategy/scripts/{script_id}",
            jwt_token=jwt_token,
        )
    except EvTradeAPIError as e:
        return {"ok": False, "error": e.detail, "status_code": e.status_code}
    return {"ok": True, "user_id": user_id, "action": "deleted", "script_id": script_id}


async def _init_trading_day(jwt_token: str, trading_day: str) -> dict:
    """系统日初（⚠️ 已被 FastAPI gateway 二次确认）.

    Args:
        trading_day: YYYYMMDD 交易日
    """
    user_id = decode_user_id(jwt_token)
    try:
        data = await call_evtrade(
            method="POST",
            path="/api/admin/init",
            jwt_token=jwt_token,
            params={"trading_day": trading_day},
        )
    except EvTradeAPIError as e:
        return {"ok": False, "error": e.detail, "status_code": e.status_code}
    return {"ok": True, "user_id": user_id, "init_result": data}


async def _set_user_role(jwt_token: str, user_id: int, new_role: str) -> dict:
    """改用户角色（TODO: EvTrade 端点缺失 — 暂返回 not_implemented）.

    详见 `openspec/changes/2026-08-23-ai-agent-panel/proposal.md` §影响面
    和 `openspec/changes/2026-08-23-ai-agent-panel/tasks.md` A2b TODO。
    """
    return {
        "ok": False,
        "error": (
            "set_user_role not yet implemented: EvTrade users API "
            "lacks PUT /api/users/{user_id}/role endpoint. "
            "Tracked in ai-agent-panel/tasks.md A2b TODO."
        ),
        "status_code": 501,
    }


# ─── 注册 ─────────────────────────────────────────────────────────
register(
    name="delete_strategy_script",
    description=(
        "⚠️ REQUIRES_USER_CONFIRMATION — 删除策略脚本（不可恢复）。"
        "实际执行前会由前端弹 Modal 让用户确认。"
    ),
    schema={
        "type": "object",
        "properties": {
            "script_id": {"type": "integer", "description": "要删除的脚本 id"},
        },
        "required": ["jwt_token", "script_id"],
        "additionalProperties": False,
    },
    handler=_delete_strategy_script,
    high_risk=True,
    toolset="admin",
)

register(
    name="init_trading_day",
    description=(
        "⚠️ REQUIRES_USER_CONFIRMATION — 系统日初（切换交易日，触发对账）。"
        "仅 admin 可调用；实际执行前会由前端弹 Modal 让用户确认。"
    ),
    schema={
        "type": "object",
        "properties": {
            "trading_day": {"type": "string", "description": "YYYYMMDD 交易日"},
        },
        "required": ["jwt_token", "trading_day"],
        "additionalProperties": False,
    },
    handler=_init_trading_day,
    high_risk=True,
    toolset="admin",
)

register(
    name="set_user_role",
    description=(
        "⚠️ REQUIRES_USER_CONFIRMATION — 修改用户的系统角色（admin/trader/viewer）。"
        "仅 admin 可调用；实际执行前会由前端弹 Modal 让用户确认。"
        "**暂未实现**（EvTrade users API 缺 PUT /api/users/{user_id}/role 端点）。"
    ),
    schema={
        "type": "object",
        "properties": {
            "user_id": {"type": "integer", "description": "目标用户 id"},
            "new_role": {"type": "string", "enum": ["admin", "trader", "viewer"]},
        },
        "required": ["jwt_token", "user_id", "new_role"],
        "additionalProperties": False,
    },
    handler=_set_user_role,
    high_risk=True,
    toolset="admin",
)
