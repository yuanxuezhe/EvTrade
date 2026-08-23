"""
server/mcp/_registry.py — 自实现 MCP-style tool registry

不依赖 mcp SDK（避免装包破坏 uvicorn 版本约束）。

每个 tool 是一个 dict:
    {
        "name": str,
        "description": str,           # LLM 用 description 决定何时调用
        "schema": dict,                # JSON Schema for parameters (LLM 生成参数用)
        "handler": async fn(jwt_token, **params) -> dict,
        "high_risk": bool,             # True → 返回 confirmation_required
        "toolset": str,                # read-only / write / trade / admin
    }

FastAPI agent.py 通过 `TOOL_REGISTRY` 查询 + 调用。
"""
from typing import Any, Awaitable, Callable, TypedDict

ToolHandler = Callable[..., Awaitable[dict[str, Any]]]


class ToolDef(TypedDict):
    name: str
    description: str
    schema: dict[str, Any]
    handler: ToolHandler
    high_risk: bool
    toolset: str


TOOL_REGISTRY: dict[str, ToolDef] = {}


def register(
    *,
    name: str,
    description: str,
    schema: dict[str, Any],
    handler: ToolHandler,
    high_risk: bool = False,
    toolset: str = "default",
) -> None:
    """注册一个 tool — 重复 name 抛 RuntimeError（防 LLM 拿到歧义工具）"""
    if name in TOOL_REGISTRY:
        raise RuntimeError(f"tool '{name}' already registered")
    TOOL_REGISTRY[name] = ToolDef(
        name=name,
        description=description,
        schema=schema,
        handler=handler,
        high_risk=high_risk,
        toolset=toolset,
    )


def is_high_risk(name: str) -> bool:
    """判断 tool 是否高危（前端二次确认）"""
    td = TOOL_REGISTRY.get(name)
    return bool(td and td.get("high_risk"))


def list_tools() -> list[dict[str, Any]]:
    """列所有 tool 给 LLM 用（仅 name/description/schema/toolset）"""
    return [
        {
            "name": td["name"],
            "description": td["description"],
            "schema": td["schema"],
            "toolset": td.get("toolset", "default"),
        }
        for td in TOOL_REGISTRY.values()
    ]


def get_handler(name: str) -> ToolHandler | None:
    td = TOOL_REGISTRY.get(name)
    return td["handler"] if td else None
