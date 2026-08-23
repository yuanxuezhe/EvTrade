"""
server/mcp/tools/write.py — 低危 write tool

| Tool | High Risk | Toolset | 描述 |
|---|---|---|---|
| save_strategy_script | 否 | write | 保存策略脚本（创建或更新） |
"""
import logging
from typing import Optional

from .._client import EvTradeAPIError, call_evtrade
from .._jwt import decode_user_id
from .._registry import register

log = logging.getLogger(__name__)


async def _save_strategy_script(
    jwt_token: str,
    name: str,
    code: str,
    description: str = "",
    params_schema: Optional[list[dict]] = None,
    is_public: bool = False,
    script_id: Optional[int] = None,
) -> dict:
    """保存策略脚本（创建或更新）.

    Args:
        name: 脚本名
        code: 策略 Python 代码
        description: 描述
        params_schema: 参数 schema (list of {key, type, min, max, default})
        is_public: 是否公开（公开后其他用户可见但只读）
        script_id: 已存在脚本的 id（None = 创建新脚本，int = 更新已有脚本）
    """
    user_id = decode_user_id(jwt_token)
    body = {
        "name": name,
        "code": code,
        "description": description,
        "params_schema": params_schema or [],
        "is_public": is_public,
    }
    if script_id is not None:
        # 更新
        try:
            data = await call_evtrade(
                method="PUT",
                path=f"/api/script-strategy/scripts/{script_id}",
                jwt_token=jwt_token,
                json_body=body,
            )
        except EvTradeAPIError as e:
            return {"ok": False, "error": e.detail, "status_code": e.status_code}
        return {"ok": True, "action": "updated", "user_id": user_id, "script": data}
    else:
        # 创建
        try:
            data = await call_evtrade(
                method="POST",
                path="/api/script-strategy/scripts",
                jwt_token=jwt_token,
                json_body=body,
            )
        except EvTradeAPIError as e:
            return {"ok": False, "error": e.detail, "status_code": e.status_code}
        return {"ok": True, "action": "created", "user_id": user_id, "script": data}


# ─── 注册 ─────────────────────────────────────────────────────────
register(
    name="save_strategy_script",
    description=(
        "保存策略脚本（创建新脚本或更新已有脚本）。"
        "如果提供 script_id 则更新已有脚本，否则创建新脚本。"
        "返回保存后的脚本详情（含 id / name / code / params_schema / is_public）。"
    ),
    schema={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "脚本名（必填）"},
            "code": {"type": "string", "description": "策略 Python 代码（必填）"},
            "description": {"type": "string", "default": "", "description": "脚本描述"},
            "params_schema": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},
                        "type": {"type": "string", "enum": ["int", "float", "choice"]},
                        "min": {"type": "number"},
                        "max": {"type": "number"},
                        "default": {},
                    },
                },
                "default": [],
            },
            "is_public": {"type": "boolean", "default": False, "description": "是否公开"},
            "script_id": {"type": "integer", "description": "已存在脚本的 id（更新用）"},
        },
        "required": ["jwt_token", "name", "code"],
        "additionalProperties": False,
    },
    handler=_save_strategy_script,
    high_risk=False,
    toolset="write",
)
